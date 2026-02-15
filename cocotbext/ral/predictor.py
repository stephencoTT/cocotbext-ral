"""Access-type-aware prediction engine for the cocotb RAL.

Operates on a RegisterModel, updating predicted field values on writes
and comparing actual vs predicted on reads.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from .register_model import RegisterModel, Register, SwAccess


@dataclass
class FieldResult:
    """Per-field comparison result."""
    field_name: str
    expected: int
    actual: int
    matched: bool


@dataclass
class PredictionResult:
    """Result of a read prediction check."""
    register_name: str
    address: int
    passed: bool
    field_results: List[FieldResult] = field(default_factory=list)
    error_messages: List[str] = field(default_factory=list)


class Predictor:
    """Maintains and checks register predictions against actual values."""

    def __init__(self, model: RegisterModel, logger_name: str = "ral"):
        self.model = model
        self.log = logging.getLogger(f"{logger_name}.predictor")

    def predict_write(self, address: int, data: int, size_bytes: int = 4):
        """Update field predictions based on a write transaction.

        Args:
            address: Register address.
            data: Written data value.
            size_bytes: Transaction size in bytes.
        """
        reg = self.model.get_register_by_address(address)
        if reg is None:
            self.log.debug(f"Write to unmapped address 0x{address:08x}, ignoring")
            return

        self.log.debug(
            f"predict_write: {reg.hierarchical_name} @ 0x{address:08x} = 0x{data:08x}"
        )

        for f in reg.fields:
            field_data = (data >> f.lsb) & f.mask

            if f.sw_access == SwAccess.RW:
                f.predicted_value = field_data
            elif f.sw_access == SwAccess.WO:
                f.predicted_value = field_data
            elif f.sw_access == SwAccess.WOCLR:
                # Write-1-to-clear: bits written as 1 clear to 0
                f.predicted_value &= ~field_data
            elif f.sw_access == SwAccess.RO:
                pass  # Read-only: writes have no effect

    def predict_read(
        self,
        address: int,
        actual_data: int,
        size_bytes: int = 4,
    ) -> PredictionResult:
        """Check actual read data against predictions.

        Args:
            address: Register address.
            actual_data: Data actually read from the bus.
            size_bytes: Transaction size in bytes.

        Returns:
            PredictionResult with per-field comparison details.
        """
        reg = self.model.get_register_by_address(address)
        if reg is None:
            self.log.debug(f"Read from unmapped address 0x{address:08x}, ignoring")
            return PredictionResult(
                register_name="<unmapped>",
                address=address,
                passed=True,
            )

        result = PredictionResult(
            register_name=reg.hierarchical_name,
            address=address,
            passed=True,
        )

        for f in reg.fields:
            actual_field = (actual_data >> f.lsb) & f.mask

            if f.is_checkable_on_read:
                matched = actual_field == f.predicted_value
                result.field_results.append(FieldResult(
                    field_name=f.name,
                    expected=f.predicted_value,
                    actual=actual_field,
                    matched=matched,
                ))
                if not matched:
                    result.passed = False
                    msg = (
                        f"{reg.hierarchical_name}.{f.name}: expected 0x{f.predicted_value:x}, "
                        f"got 0x{actual_field:x}"
                    )
                    result.error_messages.append(msg)
                    self.log.error(f"MISMATCH {msg}")
                else:
                    self.log.debug(
                        f"  {reg.hierarchical_name}.{f.name}: OK (0x{actual_field:x})"
                    )
            else:
                # RO/WO: log actual value but don't check
                self.log.debug(
                    f"  {reg.hierarchical_name}.{f.name} ({f.sw_access.name}): "
                    f"actual=0x{actual_field:x} (not checked)"
                )

        return result
