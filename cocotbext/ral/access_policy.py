"""Field access policy helpers for the data-driven runtime path.

This module keeps the surface area intentionally small for now. The main goal is
not to model every CSR semantic immediately, but to establish a single place
where access behavior lives so richer semantics can be added without spreading
special cases across the RAL and predictor code.
"""

from __future__ import annotations

from dataclasses import dataclass

from .register_model import RegisterField, SwAccess
from .state import FieldState


@dataclass(frozen=True)
class AccessPolicy:
    """Behavioral policy for a field's software-visible access semantics."""

    sw_access: SwAccess

    def apply_write(self, field: RegisterField, state: FieldState, write_value: int) -> None:
        value = write_value & field.mask
        if self.sw_access == SwAccess.RW:
            state.mirrored = value
            state.desired = value
            state.dirty = False
        elif self.sw_access == SwAccess.WO:
            state.mirrored = value
            state.desired = value
            state.dirty = False
        elif self.sw_access == SwAccess.WOCLR:
            state.mirrored &= ~value
            state.mirrored &= field.mask
            state.desired = state.mirrored
            state.dirty = False
        elif self.sw_access == SwAccess.RO:
            return

    def check_on_read(self, state: FieldState) -> bool:
        return state.check_enabled and self.sw_access in (SwAccess.RW, SwAccess.WOCLR)


class PolicyRegistry:
    """Minimal registry from field spec to runtime policy object."""

    def policy_for(self, field: RegisterField) -> AccessPolicy:
        return AccessPolicy(field.sw_access)
