"""Runtime state helpers for a more data-driven cocotb RAL.

This module intentionally does not replace the existing RegisterModel yet.
Instead, it provides a parallel runtime-state representation that can be
introduced incrementally without breaking the current public API.

The design goal is to separate:
    * immutable-ish register specification data (name, bit positions, reset,
      access policy)
    * per-instance simulation state (mirrored value, desired value,
      check enable, dirty flag)

That split makes it much easier to support multiple live RAL instances from a
single spec, richer policy engines, alias registers, and context-dependent
checking modes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .register_model import RegisterModel, RegisterField, Register


@dataclass
class FieldState:
    """Per-instance runtime state for a single field."""

    mirrored: int
    desired: int
    check_enabled: bool = True
    dirty: bool = False

    def reset(self, value: int) -> None:
        self.mirrored = value
        self.desired = value
        self.dirty = False


@dataclass
class RegisterState:
    """Per-instance runtime state for one register."""

    fields: Dict[str, FieldState]

    @property
    def predicted_value(self) -> int:
        value = 0
        for field_name, state in self.fields.items():
            field = self._field_specs[field_name]
            value |= (state.mirrored & field.mask) << field.lsb
        return value

    def attach_specs(self, specs: Dict[str, RegisterField]) -> None:
        self._field_specs = specs

    def reset(self) -> None:
        for field_name, state in self.fields.items():
            field = self._field_specs[field_name]
            state.reset(field.reset_value)


class RuntimeState:
    """Runtime state container derived from an existing RegisterModel.

    The current codebase stores prediction data directly inside RegisterField.
    This helper provides a migration path toward a more data-driven model while
    preserving the existing user-facing API.
    """

    def __init__(self, model: RegisterModel):
        self.model = model
        self._registers: Dict[int, RegisterState] = {}

        for reg in model.all_registers():
            state = RegisterState(
                fields={
                    field.name: FieldState(
                        mirrored=field.reset_value,
                        desired=field.reset_value,
                        check_enabled=True,
                        dirty=False,
                    )
                    for field in reg.fields
                }
            )
            state.attach_specs({field.name: field for field in reg.fields})
            self._registers[reg.address] = state

    def get_register_state(self, name_or_addr: int | str) -> RegisterState | None:
        reg = self.model.get_register(name_or_addr)
        if reg is None:
            return None
        return self._registers.get(reg.address)

    def reset(self) -> None:
        for reg_state in self._registers.values():
            reg_state.reset()

    def sync_from_legacy_model(self) -> None:
        """Copy values from RegisterField.predicted_value/check_enabled.

        This keeps the new runtime state usable even before the predictor and
        RAL layers are fully migrated.
        """
        for reg in self.model.all_registers():
            reg_state = self._registers[reg.address]
            for field in reg.fields:
                field_state = reg_state.fields[field.name]
                field_state.mirrored = field.predicted_value
                field_state.desired = field.predicted_value
                field_state.check_enabled = field.check_enabled

    def sync_to_legacy_model(self) -> None:
        """Push runtime state back into the existing RegisterField objects.

        This allows incremental adoption in downstream code that still consumes
        RegisterField.predicted_value directly.
        """
        for reg in self.model.all_registers():
            reg_state = self._registers[reg.address]
            for field in reg.fields:
                field_state = reg_state.fields[field.name]
                field.predicted_value = field_state.mirrored & field.mask
                field.check_enabled = field_state.check_enabled

    def set_field_mirrored(self, reg_name_or_addr: int | str, field_name: str, value: int) -> None:
        reg = self.model.get_register(reg_name_or_addr)
        if reg is None:
            raise KeyError(f"Register {reg_name_or_addr!r} not found")
        field = reg.get_field(field_name)
        if field is None:
            raise KeyError(f"Field {field_name!r} not found in {reg.name}")
        reg_state = self._registers[reg.address]
        field_state = reg_state.fields[field_name]
        field_state.mirrored = value & field.mask
        field_state.desired = value & field.mask
        field_state.dirty = False

    def disable_check(self, reg_name_or_addr: int | str, field_name: str = "") -> None:
        reg = self.model.get_register(reg_name_or_addr)
        if reg is None:
            raise KeyError(f"Register {reg_name_or_addr!r} not found")
        reg_state = self._registers[reg.address]
        if field_name:
            if field_name not in reg_state.fields:
                raise KeyError(f"Field {field_name!r} not found in {reg.name}")
            reg_state.fields[field_name].check_enabled = False
        else:
            for state in reg_state.fields.values():
                state.check_enabled = False

    def enable_check(self, reg_name_or_addr: int | str, field_name: str = "") -> None:
        reg = self.model.get_register(reg_name_or_addr)
        if reg is None:
            raise KeyError(f"Register {reg_name_or_addr!r} not found")
        reg_state = self._registers[reg.address]
        if field_name:
            if field_name not in reg_state.fields:
                raise KeyError(f"Field {field_name!r} not found in {reg.name}")
            reg_state.fields[field_name].check_enabled = True
        else:
            for state in reg_state.fields.values():
                state.check_enabled = True
