"""Runtime-backed Register Abstraction Layer.

``RuntimeRAL`` is the cocotb-facing base class. It owns a ``RegisterModel``
(immutable structural spec), a ``RuntimeState`` (mutable mirror / check
state), a ``RuntimePredictor`` (runs access policies), and a ``Checker``
(accumulates prediction pass/fail results).

One spec can back many ``RuntimeRAL`` instances with independent state,
which is the usual pattern for tiled / replicated designs.
"""

import logging
from typing import Dict, List, Optional, Tuple, Union

from .register_model import RegisterModel, Register
from .runtime_predictor import RuntimePredictor
from .state import RuntimeState
from .checker import Checker
class RuntimeRAL:
    """Register Abstraction Layer for cocotb-based verification.

    Supports active mode (driving via cocotbext masters), passive monitor
    mode, and backdoor access via HDL paths. The spec layer is immutable
    structural data; all per-instance mirror state lives in
    ``self.runtime_state``.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        name: str,
        model: RegisterModel,
        dut_handle=None,
    ):
        """Create a RuntimeRAL instance.

        Args:
            name: Unique identifier for log output (e.g. "tile_3_4").
            model: Populated RegisterModel from any loader.
            dut_handle: cocotb DUT handle, needed only for backdoor access.
        """
        self.name = name
        self.model = model
        self.dut = dut_handle
        self.log = logging.getLogger(f"ral.{name}")

        self.runtime_state = RuntimeState(model)
        self._predictor = RuntimePredictor(
            model, runtime_state=self.runtime_state,
            logger_name=f"ral.{name}",
        )
        self._checker = Checker(logger_name=f"ral.{name}", name=name)

        self._master = None
        self._protocol: Optional[str] = None
        self._monitor = None

    # ------------------------------------------------------------------
    # Master attachment (active mode)
    # ------------------------------------------------------------------

    def attach_master(self, master, protocol: str = "apb"):
        """Attach a cocotbext VIP master for driving transactions.

        Args:
            master: A cocotbext master instance. Accepted types:
                - cocotbext.apb.ApbMaster (protocol="apb")
                - cocotbext.axi.AxiLiteMaster (protocol="axil")
                - cocotbext.axi.AxiMaster (protocol="axi")
            protocol: One of "apb", "axil", "axi".
        """
        self._master = master
        self._protocol = protocol.lower()
        self.log.info(f"Attached {self._protocol.upper()} master")

    # ------------------------------------------------------------------
    # Front-door access
    # ------------------------------------------------------------------

    async def write(self, name_or_addr: Union[str, int], value: int):
        """Front-door write: drive the bus and update the mirror."""
        if self._master is None:
            raise RuntimeError("No master attached. Call attach_master() first.")

        reg = self._resolve_register(name_or_addr)
        if reg is None and isinstance(name_or_addr, str):
            raise KeyError(f"Register {name_or_addr!r} not found in model")
        addr = reg.address if reg else name_or_addr
        size_bytes = reg.size_bytes if reg else 4

        await self._protocol_write(addr, value, size_bytes)

        if reg:
            self.log.info(f"Write {reg.hierarchical_name} @ 0x{addr:08x} = 0x{value:08x}")
            self._predictor.predict_write(addr, value, size_bytes)
        else:
            self.log.debug(f"Write unmapped 0x{addr:08x} = 0x{value:08x}")

    async def read(self, name_or_addr: Union[str, int]) -> int:
        """Front-door read: drive the bus, check the prediction, and return
        the raw value. Optional backdoor cross-check if the DUT handle is
        set and the register has an HDL path."""
        if self._master is None:
            raise RuntimeError("No master attached. Call attach_master() first.")

        reg = self._resolve_register(name_or_addr)
        if reg is None and isinstance(name_or_addr, str):
            raise KeyError(f"Register {name_or_addr!r} not found in model")
        addr = reg.address if reg else name_or_addr
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

        return actual

    async def write_field(self, reg_name: str, field_name: str, value: int):
        """Read-modify-write a single field."""
        reg = self._resolve_register(reg_name)
        if reg is None:
            raise KeyError(f"Register {reg_name!r} not found")
        field = reg.get_field(field_name)
        if field is None:
            raise KeyError(f"Field {field_name!r} not found in {reg.name}")

        current = await self.read(reg.address)
        mask = field.mask << field.lsb
        new_value = (current & ~mask) | ((value & field.mask) << field.lsb)
        await self.write(reg.address, new_value)

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

    # ------------------------------------------------------------------
    # UVM-style set / update
    # ------------------------------------------------------------------

    def set_field(self, name_or_addr: Union[str, int], field_name: str, value: int) -> None:
        """Set a field's desired value in the mirror without driving the bus.

        Call :meth:`update` afterwards to push all pending desired values
        to hardware in a single bus write. Follows the UVM RAL
        ``field.set()`` pattern.

        Args:
            name_or_addr: Register name or address.
            field_name: Field name within the register.
            value: Desired field value.
        """
        reg = self.get_register(name_or_addr)
        field = reg.get_field(field_name)
        if field is None:
            raise KeyError(f"Field {field_name!r} not found in {reg.name}")
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
    def _resolve_hdl_value(raw_value, n_bits: int) -> int:
        """Resolve a cocotb BinaryValue to an integer, treating X/Z as 0."""
        result = 0
        if hasattr(raw_value, 'n_bits'):
            for i in range(raw_value.n_bits - 1, -1, -1):
                bit = raw_value.n_bits - 1 - i
                if raw_value[i].is_resolvable:
                    result |= int(raw_value[i]) << bit
        else:
            result = int(raw_value)
        return result

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
        from .register_model import Memory
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

    def reset(self):
        """Restore the mirror on every register to its reset value.

        Affects mutable runtime state only; the spec model is unchanged.
        """
        self.runtime_state.reset()
        self.log.info("Mirror reset to defaults")

    def notify_external_write(self, address: int, data: int, size_bytes: int = 4):
        """Update the mirror as if a SW-style write happened from another agent.

        Runs the value through the normal write access policy (W1C clears,
        WO stores, RO no-op, etc.). Use this when firmware or a second
        master writes to a register in this RAL's model without going
        through this RAL.
        """
        self._predictor.predict_write(address, data, size_bytes)

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

    async def _protocol_write(self, addr: int, value: int, size_bytes: int):
        if self._protocol == "apb":
            await self._master.write(addr, value)
        elif self._protocol in ("axil", "axi"):
            data_bytes = value.to_bytes(size_bytes, byteorder="little")
            await self._master.write(addr, data_bytes)
        else:
            raise RuntimeError(f"Unknown protocol: {self._protocol}")

    async def _protocol_read(self, addr: int, size_bytes: int) -> int:
        if self._protocol == "apb":
            resp = await self._master.read(addr)
            return int.from_bytes(bytes(resp), byteorder="little")
        elif self._protocol in ("axil", "axi"):
            resp = await self._master.read(addr, size_bytes)
            return int.from_bytes(bytes(resp.data), byteorder="little")
        else:
            raise RuntimeError(f"Unknown protocol: {self._protocol}")

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

                await Timer(interval_us, units="us")
                elapsed += interval_us

            raise TimeoutError(
                f"poll: {reg.hierarchical_name} did not reach "
                f"0x{expected:x} within {timeout_us}us "
                f"(last: 0x{raw:x})"
            )
        finally:
            self.enable_check(addr)
