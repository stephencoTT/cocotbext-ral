"""Top-level RAL class: model + front-door access + backdoor + monitoring.

Each RAL instance gets a unique name for logging. The RAL is protocol-agnostic
at the user API level — protocol differences are normalized internally when
a cocotbext master is attached.
"""

import logging
import warnings
from typing import Dict, List, Optional, Tuple, Union

import cocotb

from .register_model import RegisterModel, Register
from .predictor import Predictor
from .checker import Checker
from .monitor import ApbRalMonitor, AxiLiteRalMonitor, AxiRalMonitor


class RAL:
    """Register Abstraction Layer for cocotb-based verification.

    Supports active mode (driving via cocotbext masters), passive monitor
    mode, and backdoor access via HDL paths.

    Note:
        This class remains supported for compatibility, but it is now the
        legacy design path. New code should prefer IntegratedRuntimeRAL.
    """

    def __init__(
        self,
        name: str,
        model: RegisterModel,
        dut_handle=None,
    ):
        """Create a RAL instance.

        Args:
            name: Unique identifier for log output (e.g. "tensix_3_4").
            model: Populated RegisterModel from any loader.
            dut_handle: cocotb DUT handle, needed only for backdoor access.
        """
        if type(self) is RAL:
            warnings.warn(
                "cocotbext.ral.RAL is part of the legacy path. "
                "Prefer IntegratedRuntimeRAL for new code.",
                DeprecationWarning,
                stacklevel=2,
            )
        self.name = name
        self.model = model
        self.dut = dut_handle
        self.log = logging.getLogger(f"ral.{name}")

        self._predictor = Predictor(model, logger_name=f"ral.{name}")
        self._checker = Checker(logger_name=f"ral.{name}", name=name)

        self._master = None
        self._protocol = None
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
        """Front-door write: drive transaction and update predictor.

        Args:
            name_or_addr: Register name (hierarchical or leaf) or address.
            value: Data value to write.
        """
        if self._master is None:
            raise RuntimeError("No master attached. Call attach_master() first.")

        reg = self._resolve_register(name_or_addr)
        addr = reg.address if reg else name_or_addr
        size_bytes = reg.size_bytes if reg else 4

        await self._protocol_write(addr, value, size_bytes)

        if reg:
            self.log.info(f"Write {reg.hierarchical_name} @ 0x{addr:08x} = 0x{value:08x}")
            self._predictor.predict_write(addr, value, size_bytes)
        else:
            self.log.debug(f"Write unmapped 0x{addr:08x} = 0x{value:08x}")

    async def read(self, name_or_addr: Union[str, int]) -> int:
        """Front-door read: drive transaction, check prediction, optional backdoor cross-check.

        Args:
            name_or_addr: Register name (hierarchical or leaf) or address.

        Returns:
            The read data value as an integer.
        """
        if self._master is None:
            raise RuntimeError("No master attached. Call attach_master() first.")

        reg = self._resolve_register(name_or_addr)
        addr = reg.address if reg else name_or_addr
        size_bytes = reg.size_bytes if reg else 4

        actual = await self._protocol_read(addr, size_bytes)

        if reg:
            self.log.info(f"Read  {reg.hierarchical_name} @ 0x{addr:08x} -> 0x{actual:08x}")
        else:
            self.log.debug(f"Read  unmapped 0x{addr:08x} -> 0x{actual:08x}")

        if reg:
            result = self._predictor.predict_read(addr, actual, size_bytes)
            self._checker.check(result)

            # Backdoor cross-check
            if reg.has_backdoor and self.dut is not None:
                bd_value = self._backdoor_read_raw(reg)
                if bd_value is not None and bd_value != actual:
                    self.log.warning(
                        f"Backdoor mismatch on {reg.name}: "
                        f"frontdoor=0x{actual:08x}, backdoor=0x{bd_value:08x}"
                    )

        return actual

    async def write_field(self, reg_name: str, field_name: str, value: int):
        """Read-modify-write a single field.

        Args:
            reg_name: Register name.
            field_name: Field name within the register.
            value: Value to write to the field.
        """
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
                order regardless of ``values`` insertion order, which gives
                deterministic waveforms. Pass False to preserve insertion
                order.
            best_effort: When True, a failing write is captured in the
                returned dict instead of raising, and the remaining writes
                still run. When False (default), the first failure raises
                and later writes do not happen.

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
            resolved.sort(key=lambda t: (t[1].address if t[1] else (t[0] if isinstance(t[0], int) else 2**63),))

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

        ``pattern`` is an fnmatch-style glob (``"DMA*.CTRL"``) unless
        ``regex`` is given, in which case ``pattern`` is ignored and
        ``regex`` is applied via ``re.search``. Matching registers are
        written in ascending-address order.

        Raises ``KeyError`` if no register matches; pass a tighter pattern
        if you want to allow empty matches.

        Returns the list of matched hierarchical names.
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

        ``reg_pattern`` is matched the same way as :meth:`write_pattern`.
        Registers that match the pattern but lack a field named
        ``field_name`` are silently skipped (so the caller can use a broad
        pattern across heterogeneous instances).

        Raises ``KeyError`` if no register both matches the pattern and
        contains the target field.
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
        """Read every register whose hierarchical name matches the pattern.

        Returns a dict keyed by hierarchical name, in ascending-address
        order. Prediction checking applies to each read exactly as it would
        for a single-register read.
        """
        regs = self.model.find_registers(
            name=None if regex is not None else pattern, regex=regex,
        )
        if not regs:
            raise KeyError(f"No registers match pattern {pattern!r}")
        return {r.hierarchical_name: await self.read(r.address) for r in regs}

    async def read_field(self, reg_name: str, field_name: str) -> int:
        """Read a register and extract a single field value.

        Args:
            reg_name: Register name.
            field_name: Field name within the register.

        Returns:
            The field value.
        """
        reg = self._resolve_register(reg_name)
        if reg is None:
            raise KeyError(f"Register {reg_name!r} not found")
        field = reg.get_field(field_name)
        if field is None:
            raise KeyError(f"Field {field_name!r} not found in {reg.name}")

        data = await self.read(reg.address)
        return (data >> field.lsb) & field.mask

    # ------------------------------------------------------------------
    # Backdoor access
    # ------------------------------------------------------------------

    async def backdoor_read(self, name_or_addr: Union[str, int]) -> int:
        """Read a register value via HDL signal path.

        Args:
            name_or_addr: Register name or address.

        Returns:
            The register value read from the HDL hierarchy.
        """
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
        """Force a register value via HDL signal path.

        Args:
            name_or_addr: Register name or address.
            value: Value to force.
        """
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

        # Field-level backdoor write
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

        # Field-level backdoor
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
        """Create and start a passive bus monitor.

        Args:
            bus: cocotbext bus object (ApbBus, AxiLiteBus, or AxiBus).
            clock: Clock signal for sampling.
            reset: Reset signal (required for AXI protocols).
            protocol: One of "apb", "axil", "axi".
        """
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
    # Model access
    # ------------------------------------------------------------------

    def set_predicted(self, name_or_addr: Union[str, int], value: int):
        """Manually set the predicted value for an entire register."""
        reg = self._resolve_register(name_or_addr)
        if reg is None:
            raise KeyError(f"Register {name_or_addr!r} not found")
        for f in reg.fields:
            f.predicted_value = (value >> f.lsb) & f.mask

    def set_field_predicted(self, reg_name: str, field_name: str, value: int):
        """Manually set the predicted value for a single field."""
        reg = self._resolve_register(reg_name)
        if reg is None:
            raise KeyError(f"Register {reg_name!r} not found")
        field = reg.get_field(field_name)
        if field is None:
            raise KeyError(f"Field {field_name!r} not found in {reg.name}")
        field.predicted_value = value & field.mask

    def disable_check(self, name_or_addr: Union[str, int], field_name: str = ""):
        """Disable prediction checking for a register or specific field.

        Args:
            name_or_addr: Register name or address.
            field_name: If provided, disable only this field. Otherwise disable
                all fields in the register.
        """
        reg = self._resolve_register(name_or_addr)
        if reg is None:
            raise KeyError(f"Register {name_or_addr!r} not found")
        if field_name:
            field = reg.get_field(field_name)
            if field is None:
                raise KeyError(f"Field {field_name!r} not found in {reg.name}")
            field.check_enabled = False
            self.log.debug(f"Disabled check: {reg.hierarchical_name}.{field_name}")
        else:
            for f in reg.fields:
                f.check_enabled = False
            self.log.debug(f"Disabled check: {reg.hierarchical_name} (all fields)")

    def enable_check(self, name_or_addr: Union[str, int], field_name: str = ""):
        """Re-enable prediction checking for a register or specific field.

        Args:
            name_or_addr: Register name or address.
            field_name: If provided, enable only this field. Otherwise enable
                all fields in the register.
        """
        reg = self._resolve_register(name_or_addr)
        if reg is None:
            raise KeyError(f"Register {name_or_addr!r} not found")
        if field_name:
            field = reg.get_field(field_name)
            if field is None:
                raise KeyError(f"Field {field_name!r} not found in {reg.name}")
            field.check_enabled = True
            self.log.debug(f"Enabled check: {reg.hierarchical_name}.{field_name}")
        else:
            for f in reg.fields:
                f.check_enabled = True
            self.log.debug(f"Enabled check: {reg.hierarchical_name} (all fields)")

    def set_hdl_path(self, name_or_addr: Union[str, int], hdl_path: str):
        """Set the backdoor HDL path for a register."""
        reg = self._resolve_register(name_or_addr)
        if reg is None:
            raise KeyError(f"Register {name_or_addr!r} not found")
        reg.hdl_path = hdl_path

    def set_field_hdl_path(self, reg_name: str, field_name: str, hdl_path: str):
        """Set the backdoor HDL path for a field."""
        reg = self._resolve_register(reg_name)
        if reg is None:
            raise KeyError(f"Register {reg_name!r} not found")
        field = reg.get_field(field_name)
        if field is None:
            raise KeyError(f"Field {field_name!r} not found in {reg.name}")
        field.hdl_path = hdl_path

    def get_register(self, name_or_addr: Union[str, int]) -> Register:
        """Look up a register by name or address.

        Raises KeyError if not found.
        """
        reg = self._resolve_register(name_or_addr)
        if reg is None:
            raise KeyError(f"Register {name_or_addr!r} not found")
        return reg

    def reset(self):
        """Restore all model values to reset defaults."""
        self.model.reset()
        self.log.info("Model reset to defaults")

    def notify_external_write(self, address: int, data: int, size_bytes: int = 4):
        """Update predictor for writes not going through this RAL.

        Use this when another agent (e.g. firmware, another master) writes
        to registers in this RAL's model.
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
        """Resolve a name or address to a Register, or None."""
        return self.model.get_register(name_or_addr)

    async def _protocol_write(self, addr: int, value: int, size_bytes: int):
        """Drive a write via the attached master, normalizing protocol differences."""
        if self._protocol == "apb":
            # ApbMaster.write(addr, data) — data can be int
            await self._master.write(addr, value)
        elif self._protocol in ("axil", "axi"):
            # AXI masters require bytes
            data_bytes = value.to_bytes(size_bytes, byteorder="little")
            await self._master.write(addr, data_bytes)
        else:
            raise RuntimeError(f"Unknown protocol: {self._protocol}")

    async def _protocol_read(self, addr: int, size_bytes: int) -> int:
        """Drive a read via the attached master, normalizing protocol differences."""
        if self._protocol == "apb":
            # ApbMaster.read(addr) returns bytes
            resp = await self._master.read(addr)
            return int.from_bytes(bytes(resp), byteorder="little")
        elif self._protocol in ("axil", "axi"):
            # AXI masters: read(addr, length) returns response object with .data
            resp = await self._master.read(addr, size_bytes)
            return int.from_bytes(bytes(resp.data), byteorder="little")
        else:
            raise RuntimeError(f"Unknown protocol: {self._protocol}")
