"""Access-type-aware prediction engine for the cocotb RAL.

Operates on a RegisterModel, updating predicted field values on writes
and comparing actual vs predicted on reads.
"""

import logging
import warnings
from dataclasses import dataclass, field
from typing import List, Optional

from .register_model import RegisterModel, Register, SwAccess

warnings.warn(
    "cocotbext.ral.Predictor is part of the legacy path. Prefer RuntimePredictor for new code.",
    DeprecationWarning,
    stacklevel=2,
)


@dataclass
class FieldResult:
    field_name: str
    expected: int
    actual: int
    matched: bool


@dataclass
class PredictionResult:
    register_name: str
    address: int
    passed: bool
    field_results: List[FieldResult] = field(default_factory=list)
    error_messages: List[str] = field(default_factory=list)


class Predictor:
    def __init__(self, model: RegisterModel, logger_name: str = "ral"):
        self.model = model
        self.log = logging.getLogger(f"{logger_name}.predictor")

    def predict_write(self, address: int, data: int, size_bytes: int = 4):
        reg = self.model.get_register_by_address(address)
        if reg is None:
            return

        for f in reg.fields:
            field_data = (data >> f.lsb) & f.mask

            if f.sw_access == SwAccess.RW:
                f.predicted_value = field_data
            elif f.sw_access == SwAccess.WO:
                f.predicted_value = field_data
            elif f.sw_access == SwAccess.WOCLR:
                f.predicted_value &= ~field_data

    def predict_read(self, address: int, actual_data: int, size_bytes: int = 4) -> PredictionResult:
        reg = self.model.get_register_by_address(address)
        if reg is None:
            return PredictionResult(register_name="<unmapped>", address=address, passed=True)

        result = PredictionResult(register_name=reg.hierarchical_name, address=address, passed=True)

        for f in reg.fields:
            actual_field = (actual_data >> f.lsb) & f.mask

            if f.is_checkable_on_read:
                matched = actual_field == f.predicted_value
                result.field_results.append(FieldResult(f.name, f.predicted_value, actual_field, matched))
                if not matched:
                    result.passed = False

        return result
