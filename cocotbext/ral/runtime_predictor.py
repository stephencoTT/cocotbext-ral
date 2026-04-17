"""Runtime-state-based predictor for cocotbext-ral.

Operates on RuntimeState + PolicyRegistry. The spec layer
(RegisterModel / Register / RegisterField) is immutable structural data;
all mutable mirror state lives in RuntimeState.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from .access_policy import PolicyRegistry
from .register_model import RegisterModel
from .state import RuntimeState


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


class RuntimePredictor:
    """Prediction/check engine backed by RuntimeState.

    The legacy RegisterField objects remain the source of structural truth.
    RuntimeState holds all mutable prediction state.

    In addition to write prediction, this predictor also applies read side
    effects for policies such as read-clear and read-set after a successful
    read comparison.
    """

    def __init__(
        self,
        model: RegisterModel,
        runtime_state: Optional[RuntimeState] = None,
        policy_registry: Optional[PolicyRegistry] = None,
        logger_name: str = "ral",
    ):
        self.model = model
        self.runtime_state = runtime_state or RuntimeState(model)
        self.policy_registry = policy_registry or PolicyRegistry()
        self.log = logging.getLogger(f"{logger_name}.runtime_predictor")

    def predict_write(self, address: int, data: int, size_bytes: int = 4) -> None:
        reg = self.model.get_register_by_address(address)
        if reg is None:
            self.log.debug(f"Write to unmapped address 0x{address:08x}, ignoring")
            return

        reg_state = self.runtime_state.get_register_state(address)
        if reg_state is None:
            self.log.debug(f"Missing runtime state for 0x{address:08x}, ignoring")
            return

        self.log.debug(
            f"predict_write: {reg.hierarchical_name} @ 0x{address:08x} = 0x{data:08x}"
        )

        for field in reg.fields:
            field_state = reg_state.fields[field.name]
            field_data = (data >> field.lsb) & field.mask
            policy = self.policy_registry.policy_for(field)
            policy.apply_write(field, field_state, field_data)


    def predict_read(self, address: int, actual_data: int, size_bytes: int = 4) -> PredictionResult:
        reg = self.model.get_register_by_address(address)
        if reg is None:
            self.log.debug(f"Read from unmapped address 0x{address:08x}, ignoring")
            return PredictionResult(register_name="<unmapped>", address=address, passed=True)

        reg_state = self.runtime_state.get_register_state(address)
        if reg_state is None:
            self.log.debug(f"Missing runtime state for 0x{address:08x}, ignoring")
            return PredictionResult(register_name=reg.hierarchical_name, address=address, passed=True)

        result = PredictionResult(
            register_name=reg.hierarchical_name,
            address=address,
            passed=True,
        )

        for field in reg.fields:
            field_state = reg_state.fields[field.name]
            policy = self.policy_registry.policy_for(field)
            actual_field = (actual_data >> field.lsb) & field.mask

            if policy.check_on_read(field, field_state):
                expected = field_state.mirrored & field.mask
                matched = actual_field == expected
                result.field_results.append(
                    FieldResult(
                        field_name=field.name,
                        expected=expected,
                        actual=actual_field,
                        matched=matched,
                    )
                )
                if not matched:
                    result.passed = False
                    msg = (
                        f"{reg.hierarchical_name}.{field.name}: expected 0x{expected:x}, "
                        f"got 0x{actual_field:x}"
                    )
                    result.error_messages.append(msg)
                    self.log.error(f"MISMATCH {msg}")
                else:
                    self.log.debug(
                        f"  {reg.hierarchical_name}.{field.name}: OK (0x{actual_field:x})"
                    )
            else:
                self.log.debug(
                    f"  {reg.hierarchical_name}.{field.name}: actual=0x{actual_field:x} (not checked)"
                )

            policy.apply_read_side_effect(field, field_state)

        return result
