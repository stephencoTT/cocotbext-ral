from typing import IO, Optional, Union

from .backdoor import BackdoorResolver
from .debug import dump_state, diff_state
from .rmw_policy import assess_field_rmw
from .safe_runtime_ral import SafeRuntimeRAL
from .transaction_logger import TransactionLogger, FieldDetail


class IntegratedRuntimeRAL(SafeRuntimeRAL):
    """Runtime RAL with backdoor resolution, debug helpers, and transaction logging.

    This class is intended as the forward-looking entry point for the new
    runtime-backed architecture. It layers together:
      * RuntimeState-backed prediction/checking
      * conservative RMW protection for field writes
      * pluggable backdoor path resolution
      * optional register transaction file logging

    Transaction logging is enabled by passing ``txn_log=True`` (writes to
    ``register_txns.log``) or ``txn_log="path/to/file.log"`` when
    constructing the instance.
    """

    def __init__(
        self,
        name,
        model,
        dut_handle=None,
        backdoor_resolver: Optional[BackdoorResolver] = None,
        txn_log: Union[bool, str, IO, None] = None,
    ):
        super().__init__(name, model, dut_handle)
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
    # Master attachment (captures interface path for logging)
    # ------------------------------------------------------------------

    def attach_master(self, master, protocol: str = "apb"):
        """Attach a cocotbext VIP master and record its HDL path for logging."""
        super().attach_master(master, protocol)
        # Try to extract the HDL path from the master's bus object
        self._interface_path = self._extract_interface_path(master)

        if self._txn_logger is not None:
            self._txn_logger.write_header(
                ral_name=self.name,
                protocol=protocol,
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
    # Backdoor resolution
    # ------------------------------------------------------------------

    def resolve_register_backdoor_path(self, name_or_addr):
        reg = self.get_register(name_or_addr)
        return self.backdoor_resolver.resolve_register_path(reg)

    def resolve_field_backdoor_path(self, reg_name, field_name):
        reg = self.get_register(reg_name)
        field = reg.get_field(field_name)
        if field is None:
            raise KeyError(f"Field {field_name!r} not found in {reg.name}")
        return self.backdoor_resolver.resolve_field_path(reg, field)

    # ------------------------------------------------------------------
    # Debug helpers
    # ------------------------------------------------------------------

    def dump_runtime_state(self) -> str:
        return dump_state(self.runtime_state)

    def diff_runtime_state(self, actual: int, address: int) -> str:
        return diff_state(self.runtime_state, actual, address)

    # ------------------------------------------------------------------
    # Transaction-logged overrides
    # ------------------------------------------------------------------

    async def write(self, name_or_addr: Union[str, int], value: int):
        """Front-door write with optional transaction logging."""
        if self._txn_logger is None:
            return await super().write(name_or_addr, value)

        reg = self._resolve_register(name_or_addr)
        mirror_before = reg.predicted_value if reg else 0

        # Drive the actual write via the parent class
        await super().write(name_or_addr, value)

        mirror_after = reg.predicted_value if reg else 0

        # Build field details
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
            address=reg.address if reg else name_or_addr,
            data=value,
            size_bits=reg.size_bits if reg else 32,
            protocol=self._protocol or "unknown",
            interface=self._interface_path,
            mirror_before=mirror_before,
            mirror_after=mirror_after,
            fields=field_details,
            backdoor_path=bd_path,
        )

    async def read(self, name_or_addr: Union[str, int]) -> int:
        """Front-door read with optional transaction logging."""
        if self._txn_logger is None:
            return await super().read(name_or_addr)

        reg = self._resolve_register(name_or_addr)

        # Capture mirror BEFORE the read (predict_read may apply side effects)
        mirror_value = reg.predicted_value if reg else 0
        expected_full = mirror_value

        # Check if checking is enabled for any field
        checking_enabled = True
        if reg:
            reg_state = self.runtime_state.get_register_state(reg.address)
            if reg_state:
                checking_enabled = any(
                    fs.check_enabled for fs in reg_state.fields.values()
                )

        # Drive the actual read via the parent class
        actual = await super().read(name_or_addr)

        # Determine pass/fail from the prediction result
        passed = None
        error_messages = []
        field_details = []
        if reg:
            # Re-read the prediction result by examining field states
            # (the parent class already ran predict_read and checked)
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
            address=reg.address if reg else name_or_addr,
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

    async def write_field(self, reg_name: str, field_name: str, value: int):
        """RMW field write with optional transaction logging."""
        if self._txn_logger is None:
            return await super().write_field(reg_name, field_name, value)

        reg = self._resolve_register(reg_name)
        if reg is None:
            raise KeyError(f"Register {reg_name!r} not found")
        field_obj = reg.get_field(field_name)
        if field_obj is None:
            raise KeyError(f"Field {field_name!r} not found in {reg.name}")

        mirror_before = reg.predicted_value
        assessment = assess_field_rmw(reg, field_name)

        # Drive the actual write_field via the parent class
        # (SafeRuntimeRAL.write_field does: assess -> read -> modify -> write)
        # We need the RMW read value, so we capture it by reading first
        rmw_read_value = await self.read(reg.address)
        mask = field_obj.mask << field_obj.lsb
        full_write_value = (rmw_read_value & ~mask) | ((value & field_obj.mask) << field_obj.lsb)

        # Now do the write (skip the parent write_field since we already did the read)
        await self.write(reg.address, full_write_value)

        mirror_after = reg.predicted_value

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
