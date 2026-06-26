"""Runtime-backed Register Abstraction Layer.

``RuntimeRAL`` is the single cocotb-facing RAL class. It owns a
``RegisterModel`` (immutable structural spec), a ``RuntimeState`` (mutable
mirror / check state), a ``RuntimePredictor`` (runs access policies), and a
``Checker`` (accumulates prediction pass/fail results), and layers on
conservative read-modify-write safety, pluggable backdoor path resolution,
debug helpers, and optional transaction logging.

One spec can back many ``RuntimeRAL`` instances with independent state,
which is the usual pattern for tiled / replicated designs.
"""

import logging
from typing import IO, Any, Dict, List, Optional, Tuple, Union

from .backdoor import BackdoorResolver
from .checker import Checker
from .debug import dump_state, diff_state
from .register_model import RegisterModel, Register
from .rmw_policy import assess_field_rmw
from .runtime_predictor import RuntimePredictor
from .state import RuntimeState
from .transaction_logger import TransactionLogger, FieldDetail


class RuntimeRAL:
    """Register Abstraction Layer for cocotb-based verification.

    Supports active mode (driving via cocotbext masters), passive monitor
    mode, and backdoor access via HDL paths. The spec layer is immutable
    structural data; all per-instance mirror state lives in
    ``self.runtime_state``.

    Field writes use a conservatively checked read-modify-write sequence
    that refuses to corrupt neighboring fields in mixed-access registers.
    Pass ``txn_log=True`` (writes to ``register_txns.log``) or
    ``txn_log="path/to/file.log"`` to enable per-transaction file logging.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        name: str,
        model: RegisterModel,
        dut_handle=None,
        backdoor_resolver: Optional[BackdoorResolver] = None,
        txn_log: Union[bool, str, IO, None] = None,
        data_width: int = 4,
        address_offset: int = 0,
        check_response: bool = False,
        raise_on_bus_error: bool = True,
    ):
        """Create a RuntimeRAL instance.

        Args:
            name: Unique identifier for log output (e.g. "tile_3_4").
            model: Populated RegisterModel from any loader.
            dut_handle: cocotb DUT handle, needed only for backdoor access.
            backdoor_resolver: Resolver mapping spec HDL paths onto the
                concrete instance hierarchy. Defaults to a passthrough
                ``BackdoorResolver``.
            txn_log: Enable per-transaction file logging. ``True`` writes to
                ``register_txns.log``; a string is treated as a file path; a
                file-like object is written to directly. ``None`` / ``False``
                disables logging (zero overhead).
            data_width: Bus data width in bytes (default 4). Registers wider
                than this are split into multiple beats on APB.
            address_offset: Constant added to every bus address. Lets one
                ``RegisterModel`` be driven through several physical maps
                (e.g. the same block reachable from two interfaces at
                different bases) by using one RAL per map.
            check_response: When True, inspect the VIP response object after
                each access and flag AXI error responses (SLVERR/DECERR).
            raise_on_bus_error: When response checking is on, raise (True,
                default) or just log (False) on a bus error.
        """
        self.name = name
        self.model = model
        self.dut = dut_handle
        self.log = logging.getLogger(f"ral.{name}")

        self._data_width_bytes = data_width
        self._address_offset = address_offset
        self._check_bus_resp = check_response
        self._raise_on_bus_error = raise_on_bus_error
        # Pre/post read/write hooks: each callback is fn(ral, target, value).
        self._callbacks: Dict[str, List] = {
            "pre_write": [], "post_write": [], "pre_read": [], "post_read": [],
        }

        self.runtime_state = RuntimeState(model)
        self._predictor = RuntimePredictor(
            model, runtime_state=self.runtime_state,
            logger_name=f"ral.{name}",
        )
        self._checker = Checker(logger_name=f"ral.{name}", name=name)

        self._master: Any = None
        self._protocol: Optional[str] = None
        self._monitor: Any = None

        self.backdoor_resolver = backdoor_resolver or BackdoorResolver()
        self._txn_logger: Optional[TransactionLogger] = None
        self._interface_path: str = ""

        if txn_log is True:
            self._txn_logger = TransactionLogger("register_txns.log")
        elif isinstance(txn_log, str):
            self._txn_logger = TransactionLogger(txn_log)
        elif txn_log is not None and txn_log is not False:
            # Assume file-like object
            self._txn_logger = TransactionLogger(txn_log)

    # ------------------------------------------------------------------
    # Master attachment (active mode)
    # ------------------------------------------------------------------

    def attach_master(self, master, protocol: str = "apb", interface: str = ""):
        """Attach a cocotbext VIP master for driving transactions.

        Args:
            master: A cocotbext master instance. Accepted types:
                - cocotbext.apb.ApbMaster (protocol="apb")
                - cocotbext.axi.AxiLiteMaster (protocol="axil")
                - cocotbext.axi.AxiMaster (protocol="axi")
            protocol: One of "apb", "axil", "axi".
            interface: HDL path of the bus interface (e.g. "dut.sim_axi"),
                recorded in the transaction log. If omitted, it is extracted
                from the master object (best-effort).
        """
        self._master = master
        self._protocol = protocol.lower()
        self.log.info(f"Attached {self._protocol.upper()} master")

        self._interface_path = interface or self._extract_interface_path(master)
        if self._txn_logger is not None:
            self._txn_logger.write_header(
                ral_name=self.name,
                protocol=self._protocol,
                interface=self._interface_path,
                model_name=self.model.name,
                register_count=self.model.register_count,
            )

    @staticmethod
    def _extract_interface_path(master) -> str:
        """Best-effort extraction of the bus HDL path from a cocotbext master."""
        # cocotbext-axi masters expose .bus which has ._entity or ._name
        for attr in ("bus", "_bus"):
            bus = getattr(master, attr, None)
            if bus is not None:
                for path_attr in ("_path", "_name", "_entity"):
                    path = getattr(bus, path_attr, None)
                    if path and isinstance(path, str):
                        return path
                # Try the bus's signals for a path hint
                for sig_attr in ("awaddr", "araddr", "paddr"):
                    sig = getattr(bus, sig_attr, None)
                    if sig is not None:
                        sig_path = getattr(sig, "_path", str(sig))
                        # Strip the signal name to get the bus path
                        if "." in sig_path:
                            return sig_path.rsplit(".", 1)[0]
        return "<unknown>"

    # ------------------------------------------------------------------
    # Front-door access
    # ------------------------------------------------------------------

    async def write(self, name_or_addr: Union[str, int], value: int):
        """Front-door write: drive the bus and update the mirror.

        When transaction logging is enabled, the write is recorded with a
        per-field before/after breakdown.
        """
        if self._txn_logger is None:
            await self._write_core(name_or_addr, value)
            return

        reg = self._resolve_register(name_or_addr)
        mirror_before = self._mirror_of(reg) if reg else 0

        await self._write_core(name_or_addr, value)

        mirror_after = self._mirror_of(reg) if reg else 0

        field_details = []
        if reg:
            for f in reg.fields:
                new_val = (mirror_after >> f.lsb) & f.mask
                old_val = (mirror_before >> f.lsb) & f.mask
                field_details.append(FieldDetail(
                    name=f.name, lsb=f.lsb, msb=f.msb,
                    value=new_val, previous=old_val,
                ))

        bd_path = ""
        if reg and self.backdoor_resolver:
            bd_path = self.backdoor_resolver.resolve_register_path(reg) or ""

        self._txn_logger.log_write(
            reg=reg,
            address=reg.address if reg else name_or_addr,  # type: ignore[arg-type]
            data=value,
            size_bits=reg.size_bits if reg else 32,
            protocol=self._protocol or "unknown",
            interface=self._interface_path,
            mirror_before=mirror_before,
            mirror_after=mirror_after,
            fields=field_details,
            backdoor_path=bd_path,
        )

    async def _write_core(self, name_or_addr: Union[str, int], value: int):
        """Drive the bus and update the mirror (no transaction logging)."""
        if self._master is None:
            raise RuntimeError("No master attached. Call attach_master() first.")

        self._fire("pre_write", name_or_addr, value)

        reg = self._resolve_register(name_or_addr)
        if reg is None and isinstance(name_or_addr, str):
            raise KeyError(f"Register {name_or_addr!r} not found in model")
        addr = reg.address if reg else name_or_addr
        assert isinstance(addr, int)  # guaranteed: unmapped str names raised above
        size_bytes = reg.size_bytes if reg else 4

        await self._protocol_write(addr, value, size_bytes)

        if reg:
            self.log.info(f"Write {reg.hierarchical_name} @ 0x{addr:08x} = 0x{value:08x}")
            self._predictor.predict_write(addr, value, size_bytes)
        else:
            self.log.debug(f"Write unmapped 0x{addr:08x} = 0x{value:08x}")

        self._fire("post_write", name_or_addr, value)

    async def read(self, name_or_addr: Union[str, int]) -> int:
        """Front-door read: drive the bus, check the prediction, and return
        the raw value. Optional backdoor cross-check if the DUT handle is
        set and the register has an HDL path.

        When transaction logging is enabled, the read is recorded with a
        per-field expected/actual breakdown and pass/fail status.
        """
        if self._txn_logger is None:
            return await self._read_core(name_or_addr)

        reg = self._resolve_register(name_or_addr)

        # Capture mirror BEFORE the read (predict_read may apply side effects)
        mirror_value = self._mirror_of(reg) if reg else 0
        expected_full = mirror_value

        reg_state = None
        checking_enabled = True
        if reg:
            reg_state = self.runtime_state.get_register_state(reg.address)
            if reg_state:
                checking_enabled = any(
                    fs.check_enabled for fs in reg_state.fields.values()
                )

        # Drive the actual read (runs predict_read + check internally)
        actual = await self._read_core(name_or_addr)

        passed = None
        error_messages = []
        field_details = []
        if reg:
            for f in reg.fields:
                actual_field = (actual >> f.lsb) & f.mask
                expected_field = (mirror_value >> f.lsb) & f.mask
                is_checkable = f.is_checkable_on_read
                if reg_state:
                    fs = reg_state.fields.get(f.name)
                    if fs and not fs.check_enabled:
                        is_checkable = False

                if is_checkable:
                    matched = actual_field == expected_field
                    field_details.append(FieldDetail(
                        name=f.name, lsb=f.lsb, msb=f.msb,
                        value=actual_field, expected=expected_field,
                        matched=matched,
                    ))
                    if not matched:
                        error_messages.append(
                            f"{reg.hierarchical_name}.{f.name}: "
                            f"expected 0x{expected_field:X}, got 0x{actual_field:X}"
                        )
                else:
                    field_details.append(FieldDetail(
                        name=f.name, lsb=f.lsb, msb=f.msb,
                        value=actual_field,
                    ))

            if checking_enabled:
                passed = len(error_messages) == 0

        bd_path = ""
        if reg and self.backdoor_resolver:
            bd_path = self.backdoor_resolver.resolve_register_path(reg) or ""

        self._txn_logger.log_read(
            reg=reg,
            address=reg.address if reg else name_or_addr,  # type: ignore[arg-type]
            data=actual,
            size_bits=reg.size_bits if reg else 32,
            protocol=self._protocol or "unknown",
            interface=self._interface_path,
            mirror_value=mirror_value,
            expected_full=expected_full,
            passed=passed,
            checking_enabled=checking_enabled,
            fields=field_details,
            error_messages=error_messages,
            backdoor_path=bd_path,
        )
        return actual

    async def _read_core(self, name_or_addr: Union[str, int]) -> int:
        """Drive the bus, check the prediction, return the raw value
        (no transaction logging)."""
        if self._master is None:
            raise RuntimeError("No master attached. Call attach_master() first.")

        self._fire("pre_read", name_or_addr, None)

        reg = self._resolve_register(name_or_addr)
        if reg is None and isinstance(name_or_addr, str):
            raise KeyError(f"Register {name_or_addr!r} not found in model")
        addr = reg.address if reg else name_or_addr
        assert isinstance(addr, int)  # guaranteed: unmapped str names raised above
        size_bytes = reg.size_bytes if reg else 4

        actual = await self._protocol_read(addr, size_bytes)

        if reg:
            self.log.info(f"Read  {reg.hierarchical_name} @ 0x{addr:08x} -> 0x{actual:08x}")
            result = self._predictor.predict_read(addr, actual, size_bytes)
            self._checker.check(result)

            if reg.has_backdoor and self.dut is not None:
                bd_value = self._backdoor_read_raw(reg)
                if bd_value is not None and bd_value != actual:
                    self.log.warning(
                        f"Backdoor mismatch on {reg.name}: "
                        f"frontdoor=0x{actual:08x}, backdoor=0x{bd_value:08x}"
                    )
        else:
            self.log.debug(f"Read  unmapped 0x{addr:08x} -> 0x{actual:08x}")

        self._fire("post_read", name_or_addr, actual)
        return actual

    # ------------------------------------------------------------------
    # Callbacks (pre/post read/write hooks)
    # ------------------------------------------------------------------

    def add_callback(self, event: str, fn) -> None:
        """Register a hook fired around bus access.

        ``event`` is one of ``"pre_write"``, ``"post_write"``, ``"pre_read"``,
        ``"post_read"``. The callback is invoked as ``fn(ral, target, value)``
        where ``target`` is the register name/address and ``value`` is the
        written value (writes), the read value (``post_read``), or ``None``
        (``pre_read``). Field-level and RMW accesses fire the hooks for the
        underlying register read/write they perform.
        """
        if event not in self._callbacks:
            raise ValueError(
                f"Unknown callback event {event!r}; expected one of "
                f"{sorted(self._callbacks)}"
            )
        self._callbacks[event].append(fn)

    def _fire(self, event: str, target, value) -> None:
        for fn in self._callbacks[event]:
            fn(self, target, value)

    async def write_field(
        self,
        reg_name: str,
        field_name: str,
        value: Union[int, str],
        *,
        partial: bool = False,
    ):
        """Write a field using a conservatively checked RMW sequence.

        The read-modify-write is refused if it could corrupt a neighboring
        field in a mixed-access register (see :func:`assess_field_rmw`).
        When transaction logging is enabled, the whole RMW renders as a
        single ``WRITE_FIELD`` entry with the internal bus read + write-back
        nested beneath it.

        ``value`` may be a symbolic enum name when the field has an
        enumeration (resolved via :meth:`RegisterField.enum_value`).

        ``partial=True`` requests a byte-enable (strobe) write that skips the
        read-modify-write entirely -- valid only when the field occupies whole
        bytes (``lsb`` and ``width`` are byte multiples), in which case no
        other field can share those bytes. If the field is not byte-aligned
        the request falls back to a normal checked RMW.

        Raises:
            KeyError: If the register or field is unknown.
            RuntimeError: If the read-modify-write update is unsafe.
        """
        reg = self._resolve_register(reg_name)
        if reg is None:
            raise KeyError(f"Register {reg_name!r} not found")
        field_obj = reg.get_field(field_name)
        if field_obj is None:
            raise KeyError(f"Field {field_name!r} not found in {reg.name}")

        if isinstance(value, str):
            value = field_obj.enum_value(value)

        # Byte-strobe partial write: a byte-aligned, byte-sized field fills
        # whole bytes that no other field can share, so we can drive just
        # those bytes and let the bus byte-enables handle the rest -- no RMW.
        if partial and field_obj.lsb % 8 == 0 and field_obj.width % 8 == 0:
            self._fire("pre_write", reg_name, value)
            byte_off = field_obj.lsb // 8
            n_bytes = field_obj.width // 8
            await self._protocol_write(
                reg.address, value & field_obj.mask, n_bytes, byte_offset=byte_off,
            )
            self.runtime_state.set_field_mirrored(reg.address, field_name, value & field_obj.mask)
            self.log.info(
                f"Write(strobe) {reg.hierarchical_name}.{field_name} = 0x{value:x}"
            )
            self._fire("post_write", reg_name, value)
            return

        # Safety check FIRST -- raise before any bus activity.
        assessment = assess_field_rmw(reg, field_name)
        if not assessment.safe:
            reasons = "; ".join(assessment.reasons)
            raise RuntimeError(
                f"Unsafe RMW on {reg.hierarchical_name}.{field_name}: {reasons}"
            )

        if self._txn_logger is None:
            current = await self.read(reg.address)
            mask = field_obj.mask << field_obj.lsb
            new_value = (current & ~mask) | ((value & field_obj.mask) << field_obj.lsb)
            await self.write(reg.address, new_value)
            return

        mirror_before = self._mirror_of(reg)

        # RMW sequence: the internal read and write-back are buffered by the
        # logger and rendered as children of the WRITE_FIELD entry, so a
        # single field write is one log entry, not three.
        self._txn_logger.begin_rmw()
        try:
            rmw_read_value = await self.read(reg.address)
            mask = field_obj.mask << field_obj.lsb
            full_write_value = (rmw_read_value & ~mask) | ((value & field_obj.mask) << field_obj.lsb)
            await self.write(reg.address, full_write_value)
        except BaseException:
            self._txn_logger.end_rmw()  # discard orphaned children on failure
            raise

        mirror_after = self._mirror_of(reg)

        bd_path = ""
        if self.backdoor_resolver:
            bd_path = self.backdoor_resolver.resolve_register_path(reg) or ""

        self._txn_logger.log_write_field(
            reg=reg,
            field_obj=field_obj,
            field_value=value,
            full_write_value=full_write_value,
            rmw_read_value=rmw_read_value,
            size_bits=reg.size_bits,
            protocol=self._protocol or "unknown",
            interface=self._interface_path,
            mirror_before=mirror_before,
            mirror_after=mirror_after,
            rmw_safe=assessment.safe,
            rmw_reasons=assessment.reasons,
            backdoor_path=bd_path,
        )

    async def read_field(self, reg_name: str, field_name: str) -> int:
        """Read a register and return a single field value."""
        reg = self._resolve_register(reg_name)
        if reg is None:
            raise KeyError(f"Register {reg_name!r} not found")
        field = reg.get_field(field_name)
        if field is None:
            raise KeyError(f"Field {field_name!r} not found in {reg.name}")

        data = await self.read(reg.address)
        return (data >> field.lsb) & field.mask

    async def read_field_name(self, reg_name: str, field_name: str) -> Optional[str]:
        """Read a field and return its symbolic enum name (None if unmapped
        or the field has no enumeration)."""
        reg = self._resolve_register(reg_name)
        if reg is None:
            raise KeyError(f"Register {reg_name!r} not found")
        field = reg.get_field(field_name)
        if field is None:
            raise KeyError(f"Field {field_name!r} not found in {reg.name}")
        value = await self.read_field(reg_name, field_name)
        return field.enum_name(value)

    # ------------------------------------------------------------------
    # UVM-style set / update
    # ------------------------------------------------------------------

    def set_field(self, name_or_addr: Union[str, int], field_name: str, value: Union[int, str]) -> None:
        """Set a field's desired value in the mirror without driving the bus.

        Call :meth:`update` afterwards to push all pending desired values
        to hardware in a single bus write. Follows the UVM RAL
        ``field.set()`` pattern.

        Args:
            name_or_addr: Register name or address.
            field_name: Field name within the register.
            value: Desired field value (an ``int``, or a symbolic enum name
                when the field has an enumeration).
        """
        reg = self.get_register(name_or_addr)
        field = reg.get_field(field_name)
        if field is None:
            raise KeyError(f"Field {field_name!r} not found in {reg.name}")
        if isinstance(value, str):
            value = field.enum_value(value)
        reg_state = self.runtime_state.get_register_state(reg.address)
        if reg_state is None:
            raise KeyError(f"No runtime state for {reg.name}")
        field_state = reg_state.fields[field.name]
        field_state.desired = value & field.mask
        field_state.dirty = True

    async def update(self, name_or_addr: Union[str, int]) -> None:
        """Write the desired value to hardware in a single bus transaction.

        Packs all fields' desired values into a register word and drives
        one write. Follows the UVM RAL ``reg.update()`` pattern. Only
        fields marked dirty (via :meth:`set_field`) contribute; clean
        fields use their current mirrored value.

        Args:
            name_or_addr: Register name or address.
        """
        reg = self.get_register(name_or_addr)
        reg_state = self.runtime_state.get_register_state(reg.address)
        if reg_state is None:
            raise KeyError(f"No runtime state for {reg.name}")

        # Build the write value: dirty fields use desired, others use mirrored
        value = 0
        for field in reg.fields:
            fs = reg_state.fields[field.name]
            if fs.dirty:
                value |= (fs.desired & field.mask) << field.lsb
            else:
                value |= (fs.mirrored & field.mask) << field.lsb

        await self.write(reg.address, value)

        # Clear dirty flags
        for field in reg.fields:
            fs = reg_state.fields[field.name]
            fs.dirty = False

    async def write_fields(
        self,
        name_or_addr: Union[str, int],
        fields: dict,
    ) -> None:
        """Set multiple fields and write to hardware in one transaction.

        Compact form combining :meth:`set_field` + :meth:`update`::

            await ral.write_fields("REG", {
                "field_a": 1,
                "field_b": 0xFF,
                "field_c": 3,
            })

        Args:
            name_or_addr: Register name or address.
            fields: Dict mapping field name to desired value.
        """
        for field_name, value in fields.items():
            self.set_field(name_or_addr, field_name, value)
        await self.update(name_or_addr)

    # ------------------------------------------------------------------
    # Bulk / pattern-driven access
    # ------------------------------------------------------------------

    async def write_many(
        self,
        values: Dict[Union[str, int], int],
        *,
        sort: bool = True,
        best_effort: bool = False,
    ) -> Dict[Union[str, int], Optional[Exception]]:
        """Write many registers in one call.

        Args:
            values: Mapping of register name or address to value.
            sort: When True (default), writes are issued in ascending-address
                order regardless of ``values`` insertion order. Pass False
                to preserve insertion order.
            best_effort: When True, capture exceptions in the return dict
                instead of raising, and keep going. When False (default),
                the first failure raises and later writes do not happen.

        Returns:
            Dict keyed by the original ``values`` keys with each value set
            to ``None`` on success or the caught exception on failure.
        """
        resolved: List[Tuple[Union[str, int], Optional[Register], int]] = []
        for key, value in values.items():
            reg = self._resolve_register(key) if isinstance(key, (str, int)) else None
            if reg is None and not isinstance(key, int) and not best_effort:
                raise KeyError(f"Register {key!r} not found")
            resolved.append((key, reg, value))

        if sort:
            resolved.sort(key=lambda t: (
                t[1].address if t[1] else (t[0] if isinstance(t[0], int) else 2**63),
            ))

        results: Dict[Union[str, int], Optional[Exception]] = {}
        for key, reg, value in resolved:
            try:
                addr = reg.address if reg is not None else key
                await self.write(addr, value)
                results[key] = None
            except Exception as exc:
                results[key] = exc
                if not best_effort:
                    raise
        return results

    async def write_pattern(
        self,
        pattern: str,
        value: int,
        *,
        regex: Optional[str] = None,
    ) -> List[str]:
        """Write ``value`` to every register whose hierarchical name matches.

        ``pattern`` is an fnmatch glob; pass ``regex=`` for regex matching
        instead (mutually exclusive). Matched registers are written in
        ascending-address order. Raises ``KeyError`` if no register matches.
        """
        regs = self.model.find_registers(
            name=None if regex is not None else pattern, regex=regex,
        )
        if not regs:
            raise KeyError(f"No registers match pattern {pattern!r}")
        for reg in regs:
            await self.write(reg.address, value)
        return [r.hierarchical_name for r in regs]

    async def write_field_pattern(
        self,
        reg_pattern: str,
        field_name: str,
        value: int,
        *,
        regex: Optional[str] = None,
    ) -> List[str]:
        """Write ``value`` to a named field across every register that has it.

        Matched registers lacking the field are silently skipped. Raises
        ``KeyError`` if no register matches the pattern *and* has the field.
        """
        regs = self.model.find_registers(
            name=None if regex is not None else reg_pattern, regex=regex,
        )
        matched = [r for r in regs if r.get_field(field_name) is not None]
        if not matched:
            raise KeyError(
                f"No registers with field {field_name!r} match {reg_pattern!r}"
            )
        for reg in matched:
            await self.write_field(reg.hierarchical_name, field_name, value)
        return [r.hierarchical_name for r in matched]

    async def read_pattern(
        self,
        pattern: str,
        *,
        regex: Optional[str] = None,
    ) -> Dict[str, int]:
        """Read every register whose hierarchical name matches.

        Returns a dict keyed by hierarchical name, in ascending-address
        order. Prediction checking applies to each read.
        """
        regs = self.model.find_registers(
            name=None if regex is not None else pattern, regex=regex,
        )
        if not regs:
            raise KeyError(f"No registers match pattern {pattern!r}")
        return {r.hierarchical_name: await self.read(r.address) for r in regs}

    # ------------------------------------------------------------------
    # Backdoor access
    # ------------------------------------------------------------------

    async def backdoor_read(self, name_or_addr: Union[str, int]) -> int:
        """Read a register value via HDL signal path."""
        if self.dut is None:
            raise RuntimeError("No dut_handle provided for backdoor access.")
        reg = self._resolve_register(name_or_addr)
        if reg is None:
            raise KeyError(f"Register {name_or_addr!r} not found")
        value = self._backdoor_read_raw(reg)
        if value is None:
            raise RuntimeError(f"Backdoor read failed for {reg.name}")
        return value

    async def backdoor_write(self, name_or_addr: Union[str, int], value: int):
        """Force a register value via HDL signal path."""
        if self.dut is None:
            raise RuntimeError("No dut_handle provided for backdoor access.")
        reg = self._resolve_register(name_or_addr)
        if reg is None:
            raise KeyError(f"Register {name_or_addr!r} not found")

        if reg.hdl_path:
            handle = self.dut._id(reg.hdl_path, extended=False)
            if handle is not None:
                handle.value = value
                self.log.debug(f"backdoor_write: {reg.name} = 0x{value:08x}")
                return

        for f in reg.fields:
            if f.hdl_path:
                field_val = (value >> f.lsb) & f.mask
                handle = self.dut._id(f.hdl_path, extended=False)
                if handle is not None:
                    handle.value = field_val

    def _backdoor_read_raw(self, reg: Register) -> Optional[int]:
        """Read register value from HDL hierarchy. Returns None on failure."""
        if reg.hdl_path:
            try:
                handle = self.dut._id(reg.hdl_path, extended=False)
                if handle is None:
                    self.log.error(f"Backdoor path not found: {reg.hdl_path}")
                    return None
                raw = handle.value
                return self._resolve_hdl_value(raw, reg.size_bits)
            except Exception as e:
                self.log.error(f"Backdoor read failed for {reg.name}: {e}")
                return None

        value = 0
        any_success = False
        for f in reg.fields:
            if not f.hdl_path:
                continue
            try:
                handle = self.dut._id(f.hdl_path, extended=False)
                if handle is None:
                    continue
                raw = handle.value
                field_val = self._resolve_hdl_value(raw, f.width)
                value |= (field_val & f.mask) << f.lsb
                any_success = True
            except Exception as e:
                self.log.error(f"Backdoor read failed for field {f.name}: {e}")

        return value if any_success else None

    @staticmethod
    def _resolve_hdl_value(raw_value, n_bits: int = 0) -> int:
        """Resolve a cocotb handle value to an int, treating X/Z as 0.

        Works across cocotb 1.x (``handle.value`` is a ``BinaryValue``) and
        cocotb 2.x (``handle.value`` is a ``LogicArray``, on which ``int()``
        raises when any bit is X/Z). Plain ints pass straight through, which
        keeps mock/fake DUT handles in unit tests working.
        """
        if isinstance(raw_value, int):
            return raw_value

        # Fully-resolvable values: int() succeeds on BinaryValue and
        # LogicArray alike.
        try:
            return int(raw_value)
        except (ValueError, TypeError):
            pass

        # Some bits are X/Z. Fall back to the binary string and map every
        # non-'1' bit (0, x, z, u, -) to 0. ``str()`` yields the bit string
        # on both BinaryValue and LogicArray (e.g. "01XZ").
        binstr = str(raw_value)
        cleaned = "".join("1" if c == "1" else "0" for c in binstr if c in "01xXzZuU-")
        return int(cleaned, 2) if cleaned else 0

    # ------------------------------------------------------------------
    # Monitor mode (passive)
    # ------------------------------------------------------------------

    def attach_monitor(self, bus, clock, reset=None, protocol: str = "apb"):
        """Create and start a passive bus monitor."""
        # Lazy import so runtime_ral doesn't require cocotb at import time
        from .monitor import ApbRalMonitor, AxiLiteRalMonitor, AxiRalMonitor
        protocol = protocol.lower()
        if protocol == "apb":
            self._monitor = ApbRalMonitor(
                bus, clock, self._predictor, self._checker, name=self.name
            )
        elif protocol == "axil":
            self._monitor = AxiLiteRalMonitor(
                bus, clock, reset, self._predictor, self._checker, name=self.name
            )
        elif protocol == "axi":
            self._monitor = AxiRalMonitor(
                bus, clock, reset, self._predictor, self._checker, name=self.name
            )
        else:
            raise ValueError(f"Unknown protocol: {protocol!r}")

        self.log.info(f"Attached {protocol.upper()} monitor")

    # ------------------------------------------------------------------
    # Mirror / check state access
    # ------------------------------------------------------------------

    def set_predicted(self, name_or_addr: Union[str, int], value: int):
        """Raw overwrite of the mirror for every field in a register.

        Ignores access policy; use when hardware forced a value you want the
        mirror to reflect. See :meth:`notify_external_write` for a policy-
        aware alternative.
        """
        reg = self.get_register(name_or_addr)
        for f in reg.fields:
            self.runtime_state.set_field_mirrored(
                reg.address, f.name, (value >> f.lsb) & f.mask,
            )

    def set_field_predicted(self, reg_name: str, field_name: str, value: int):
        """Raw overwrite of the mirror for a single field."""
        reg = self.get_register(reg_name)
        if reg.get_field(field_name) is None:
            raise KeyError(f"Field {field_name!r} not found in {reg.name}")
        self.runtime_state.set_field_mirrored(reg.address, field_name, value)

    def disable_check(self, name_or_addr: Union[str, int], field_name: str = ""):
        """Disable prediction checking for a register or a specific field."""
        self.runtime_state.disable_check(name_or_addr, field_name)
        if field_name:
            self.log.debug(f"Disabled check: {name_or_addr}.{field_name}")
        else:
            self.log.debug(f"Disabled check: {name_or_addr} (all fields)")

    def enable_check(self, name_or_addr: Union[str, int], field_name: str = ""):
        """Re-enable prediction checking for a register or a specific field."""
        self.runtime_state.enable_check(name_or_addr, field_name)
        if field_name:
            self.log.debug(f"Enabled check: {name_or_addr}.{field_name}")
        else:
            self.log.debug(f"Enabled check: {name_or_addr} (all fields)")

    def disable_check_all(self):
        """Disable prediction checking on every register in the model.

        Useful when using the RAL purely for access abstraction and search
        without wanting any mirror-vs-actual comparisons.
        """
        for reg in self.model.all_registers():
            self.runtime_state.disable_check(reg.address)
        self.log.debug("Disabled check on every register in the model")

    def enable_check_all(self):
        """Re-enable prediction checking on every register in the model."""
        for reg in self.model.all_registers():
            self.runtime_state.enable_check(reg.address)
        self.log.debug("Enabled check on every register in the model")

    def set_hdl_path(self, name_or_addr: Union[str, int], hdl_path: str):
        """Set the backdoor HDL path for a register."""
        reg = self.get_register(name_or_addr)
        reg.hdl_path = hdl_path

    def set_field_hdl_path(self, reg_name: str, field_name: str, hdl_path: str):
        """Set the backdoor HDL path for a field."""
        reg = self.get_register(reg_name)
        field = reg.get_field(field_name)
        if field is None:
            raise KeyError(f"Field {field_name!r} not found in {reg.name}")
        field.hdl_path = hdl_path

    def get_register(self, name_or_addr: Union[str, int]) -> Register:
        """Look up a register by name or address. Raises KeyError if not found."""
        reg = self._resolve_register(name_or_addr)
        if reg is None:
            raise KeyError(f"Register {name_or_addr!r} not found")
        return reg

    def get_memory(self, name: str):
        """Look up a memory region by name, attached to this RAL for bus access.

        Returns a ``Memory`` object with async ``write(offset, data)`` and
        ``read(offset)`` methods that drive the bus through this RAL's
        master, following the UVM ``uvm_mem`` pattern.

        Raises KeyError if not found.
        """
        mem = self.model.get_memory(name)
        if mem is None:
            raise KeyError(f"Memory {name!r} not found in model")
        mem._attach_ral(self)
        return mem

    # ------------------------------------------------------------------
    # Mirror query (no bus traffic, pure Python)
    # ------------------------------------------------------------------

    def mirror(self, name_or_addr: Union[str, int]) -> int:
        """Return the full mirrored value of a register.

        Reads from RuntimeState, no bus transaction. Returns whatever the
        mirror currently holds (from prior writes, reads, or set_predicted).

        Args:
            name_or_addr: Register name or address.

        Returns:
            The mirrored register value.
        """
        reg = self.get_register(name_or_addr)
        return self._mirror_of(reg)

    def mirror_field(self, name_or_addr: Union[str, int], field_name: str) -> int:
        """Return the mirrored value of a single field.

        No bus transaction. Extracts the field from the register mirror
        using the model's field position and mask.

        Args:
            name_or_addr: Register name or address.
            field_name: Field name within the register.

        Returns:
            The field value extracted from the mirror.
        """
        reg = self.get_register(name_or_addr)
        field = reg.get_field(field_name)
        if field is None:
            raise KeyError(f"Field {field_name!r} not found in {reg.name}")
        mirror_val = self._mirror_of(reg)
        return (mirror_val >> field.lsb) & field.mask

    def mirror_fields(self, name_or_addr: Union[str, int]) -> dict:
        """Return all field values from the mirror as a dict.

        No bus transaction. Returns ``{field_name: value}`` for every
        field in the register.

        Args:
            name_or_addr: Register name or address.

        Returns:
            Dict mapping field name to mirrored value.
        """
        reg = self.get_register(name_or_addr)
        mirror_val = self._mirror_of(reg)
        return {
            f.name: (mirror_val >> f.lsb) & f.mask
            for f in reg.fields
        }

    def reset(self, domain: Optional[str] = None):
        """Restore the mirror on every register to its reset value.

        Affects mutable runtime state only; the spec model is unchanged.

        Args:
            domain: Named reset domain (e.g. ``"soft"``). ``None`` (default)
                uses each field's primary reset value; a named domain uses the
                field's per-domain value, falling back to the default.
        """
        self.runtime_state.reset(domain)
        self.log.info(f"Mirror reset to {domain or 'default'} reset values")

    def notify_external_write(self, address: int, data: int, size_bytes: int = 4):
        """Update the mirror as if a SW-style write happened from another agent.

        Runs the value through the normal write access policy (W1C clears,
        WO stores, RO no-op, etc.). Use this when firmware or a second
        master writes to a register in this RAL's model without going
        through this RAL.
        """
        self._predictor.predict_write(address, data, size_bytes)

    def notify_external_read(self, address: int, size_bytes: int = 4):
        """Update the mirror as if another agent read this register.

        Applies the same read side-effects the RAL's own :meth:`read` would
        apply (RCLR -> 0, RSET -> all-1s) without driving the bus or
        checking. Use this when firmware or a second master reads a register
        in this RAL's model -- for read-clear / read-set fields that read
        changes hardware state, so the mirror must follow to stay honest.
        Counterpart to :meth:`notify_external_write`.
        """
        self._predictor.apply_external_read(address, size_bytes)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def report(self) -> str:
        return self._checker.report()

    def has_errors(self) -> bool:
        return self._checker.has_errors()

    def raise_on_errors(self):
        self._checker.raise_on_errors()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_register(self, name_or_addr: Union[str, int]) -> Optional[Register]:
        return self.model.get_register(name_or_addr)

    def _mirror_of(self, reg: Register) -> int:
        """Current mirror value (packed 32-bit) for ``reg`` from runtime state.

        Returns 0 if the register has no runtime state (should not happen in
        practice, but kept permissive for consumer code).
        """
        reg_state = self.runtime_state.get_register_state(reg.address)
        return reg_state.predicted_value if reg_state else 0

    async def _protocol_write(
        self, addr: int, value: int, size_bytes: int, *, byte_offset: int = 0,
    ):
        """Drive a bus write.

        Applies :attr:`_address_offset` (multiple-map support). Registers
        wider than the bus data width are split into multiple beats on APB;
        AXI lets the VIP handle the byte count. ``byte_offset`` (with a
        ``size_bytes`` narrower than the register) performs a byte-aligned
        partial write that relies on the bus's native byte-enable / strobe.
        """
        addr += self._address_offset + byte_offset
        dw = self._data_width_bytes
        if self._protocol == "apb":
            if size_bytes > dw:
                word_mask = (1 << (dw * 8)) - 1
                for off in range(0, size_bytes, dw):
                    word = (value >> (off * 8)) & word_mask
                    resp = await self._master.write(addr + off, word)
                    self._check_bus_response(resp, "write", addr + off)
            else:
                resp = await self._master.write(addr, value)
                self._check_bus_response(resp, "write", addr)
        elif self._protocol in ("axil", "axi"):
            data_bytes = value.to_bytes(size_bytes, byteorder="little")
            resp = await self._master.write(addr, data_bytes)
            self._check_bus_response(resp, "write", addr)
        else:
            raise RuntimeError(f"Unknown protocol: {self._protocol}")

    async def _protocol_read(self, addr: int, size_bytes: int, *, byte_offset: int = 0) -> int:
        """Drive a bus read (see :meth:`_protocol_write` for offset/width)."""
        addr += self._address_offset + byte_offset
        dw = self._data_width_bytes
        if self._protocol == "apb":
            if size_bytes > dw:
                value = 0
                for off in range(0, size_bytes, dw):
                    resp = await self._master.read(addr + off)
                    value |= int.from_bytes(bytes(resp), byteorder="little") << (off * 8)
                return value
            resp = await self._master.read(addr)
            return int.from_bytes(bytes(resp), byteorder="little")
        elif self._protocol in ("axil", "axi"):
            resp = await self._master.read(addr, size_bytes)
            self._check_bus_response(resp, "read", addr)
            return int.from_bytes(bytes(resp.data), byteorder="little")
        else:
            raise RuntimeError(f"Unknown protocol: {self._protocol}")

    def _check_bus_response(self, resp, op: str, addr: int) -> None:
        """Inspect a VIP response object for an error response.

        No-op unless bus-response checking was enabled at construction. Reads
        ``resp.resp`` (e.g. cocotbext-axi's ``AxiResp``); a non-zero code is an
        error (AXI SLVERR/DECERR). Defensive across VIP types -- a ``resp``
        without a ``.resp`` attribute (e.g. APB) is ignored.

        NOTE: the exact response object differs per VIP and protocol; the
        front-door bus path is validated in simulation, not in the unit tests.
        """
        if not self._check_bus_resp or resp is None:
            return
        code = getattr(resp, "resp", None)
        if code is None:
            return
        try:
            bad = int(getattr(code, "value", code)) != 0
        except (TypeError, ValueError):
            return
        if bad:
            msg = f"bus {op} error at 0x{addr:08x}: resp={code!r}"
            self.log.error(msg)
            if self._raise_on_bus_error:
                raise RuntimeError(msg)

    # ------------------------------------------------------------------
    # Bringup mode
    # ------------------------------------------------------------------

    def begin_bringup(self):
        """Enter bringup mode: disable all prediction checking.

        Register writes and reads still go through the RAL (updating the
        mirror and logging transactions), but read mismatches are not
        flagged. Call :meth:`end_bringup` after the bringup sequence to
        re-enable checking.
        """
        self.disable_check_all()
        self.log.info("Bringup mode ENTERED (checking disabled)")

    def end_bringup(self):
        """Exit bringup mode: re-enable prediction checking on all registers."""
        self.enable_check_all()
        self.log.info("Bringup mode EXITED (checking enabled)")

    # ------------------------------------------------------------------
    # Coverage tracking
    # ------------------------------------------------------------------

    @property
    def coverage(self):
        """Access coverage data collected from the transaction logger.

        Returns a dict with keys: ``written_addrs``, ``read_addrs``,
        ``accessed_addrs``, ``total_registers``. Returns None if no
        transaction logger is active.
        """
        logger = getattr(self, '_txn_logger', None)
        if logger is None:
            return None

        written = set()
        read = set()
        for txn in logger._transactions:
            if "WRITE" in txn.operation:
                written.add(txn.address)
            if txn.operation == "READ":
                read.add(txn.address)
        accessed = written | read
        return {
            "total_registers": self.model.register_count,
            "accessed": len(accessed),
            "written": len(written),
            "read": len(read),
            "not_accessed": self.model.register_count - len(accessed),
            "accessed_addrs": accessed,
            "written_addrs": written,
            "read_addrs": read,
        }

    def coverage_report(self) -> str:
        """Return a formatted register access coverage summary.

        Groups results by the top two levels of the register hierarchy.
        """
        cov = self.coverage
        if cov is None:
            return "Coverage: no transaction logger active"

        lines = []
        lines.append(f"Coverage: {cov['accessed']}/{cov['total_registers']} "
                      f"({cov['accessed']/max(cov['total_registers'],1)*100:.1f}%) "
                      f"registers accessed "
                      f"({cov['written']} written, {cov['read']} read)")

        blocks = {}
        for reg in self.model.all_registers():
            parts = reg.hierarchical_name.split(".")
            block = ".".join(parts[:2]) if len(parts) >= 2 else parts[0]
            if block not in blocks:
                blocks[block] = {"total": 0, "accessed": 0}
            blocks[block]["total"] += 1
            if reg.address in cov["accessed_addrs"]:
                blocks[block]["accessed"] += 1

        for block in sorted(blocks):
            b = blocks[block]
            pct = b["accessed"] / max(b["total"], 1) * 100
            if b["accessed"] > 0:
                lines.append(f"  {block:<50s} {b['accessed']:>4d}/{b['total']:<4d} ({pct:.0f}%)")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def poll(
        self,
        name_or_addr: Union[str, int],
        *,
        field: Optional[str] = None,
        expected: int,
        mask: Optional[int] = None,
        timeout_us: int = 100,
        interval_us: int = 5,
    ) -> int:
        """Poll a register until it matches the expected value.

        Checking is disabled during polling to avoid false mismatches on
        hardware-driven registers, then re-enabled and the mirror synced
        with the final read value.

        Args:
            name_or_addr: Register to poll.
            field: If given, extract and compare only this field.
            expected: Value (or field value) to wait for.
            mask: Bitmask applied before comparison (ignored if ``field`` set).
            timeout_us: Maximum polling duration in microseconds.
            interval_us: Delay between reads in microseconds.

        Returns:
            The final raw read value.

        Raises:
            TimeoutError: If not matched within the timeout.
        """
        from cocotb.triggers import Timer

        reg = self.get_register(name_or_addr)
        addr = reg.address

        self.disable_check(addr)
        elapsed = 0
        raw = 0
        try:
            while elapsed < timeout_us:
                raw = await self.read(addr)

                if field is not None:
                    f = reg.get_field(field)
                    if f is None:
                        raise KeyError(f"Field {field!r} not in {reg.name}")
                    val = (raw >> f.lsb) & f.mask
                elif mask is not None:
                    val = raw & mask
                else:
                    val = raw

                if val == expected:
                    self.log.info(
                        f"poll: {reg.hierarchical_name} matched "
                        f"0x{expected:x} after ~{elapsed}us"
                    )
                    self.set_predicted(addr, raw)
                    return raw

                # Positional unit arg works on both cocotb 1.x (`units=`)
                # and cocotb 2.x (`unit=`), which renamed the keyword.
                await Timer(interval_us, "us")
                elapsed += interval_us

            raise TimeoutError(
                f"poll: {reg.hierarchical_name} did not reach "
                f"0x{expected:x} within {timeout_us}us "
                f"(last: 0x{raw:x})"
            )
        finally:
            self.enable_check(addr)

    # ------------------------------------------------------------------
    # Backdoor path resolution
    # ------------------------------------------------------------------

    def resolve_register_backdoor_path(self, name_or_addr):
        """Resolve the concrete HDL path of a register via the resolver."""
        reg = self.get_register(name_or_addr)
        return self.backdoor_resolver.resolve_register_path(reg)

    def resolve_field_backdoor_path(self, reg_name, field_name):
        """Resolve the concrete HDL path of a field via the resolver."""
        reg = self.get_register(reg_name)
        field = reg.get_field(field_name)
        if field is None:
            raise KeyError(f"Field {field_name!r} not found in {reg.name}")
        return self.backdoor_resolver.resolve_field_path(reg, field)

    # ------------------------------------------------------------------
    # Debug helpers
    # ------------------------------------------------------------------

    def dump_runtime_state(self) -> str:
        """Return a formatted dump of the current runtime mirror state."""
        return dump_state(self.runtime_state)

    def diff_runtime_state(self, actual: int, address: int) -> str:
        """Return a formatted mirror-vs-actual diff for one register."""
        return diff_state(self.runtime_state, actual, address)

    # ------------------------------------------------------------------
    # Transaction log control
    # ------------------------------------------------------------------

    def set_txn_phase(self, phase: str) -> None:
        """Annotate subsequent transactions with a phase label."""
        if self._txn_logger:
            self._txn_logger.set_phase(phase)

    def write_txn_summary(self) -> None:
        """Write the transaction summary block and flush."""
        if self._txn_logger:
            self._txn_logger.write_summary()

    def close_txn_log(self) -> None:
        """Write summary and close the transaction log file."""
        if self._txn_logger:
            self._txn_logger.write_summary()
            self._txn_logger.close()
            self._txn_logger = None
