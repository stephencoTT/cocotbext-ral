"""Field access policy helpers for the runtime path.

Supports common SystemRDL-style semantics including RW, RO, WO, W1C, W1S,
RCLR, and RSET.
"""

from dataclasses import dataclass

from .register_model import RegisterField, SwAccess
from .state import FieldState


@dataclass(frozen=True)
class AccessPolicy:
    """Behavioral policy for a field's software-visible access semantics."""

    sw_access: SwAccess

    def apply_write(self, field: RegisterField, state: FieldState, write_value: int) -> None:
        """Apply a software write to runtime field state."""
        value = write_value & field.mask

        if self.sw_access == SwAccess.RW:
            state.mirrored = value
        elif self.sw_access == SwAccess.WO:
            state.mirrored = value
        elif self.sw_access == SwAccess.W1C:
            state.mirrored &= ~value
            state.mirrored &= field.mask
        elif self.sw_access == SwAccess.W1S:
            state.mirrored |= value
            state.mirrored &= field.mask
        elif self.sw_access in (SwAccess.RO, SwAccess.RCLR, SwAccess.RSET):
            return

        state.desired = state.mirrored
        state.dirty = False

    def apply_read_side_effect(self, field: RegisterField, state: FieldState) -> None:
        """Apply any state change caused by reading the field."""
        if self.sw_access == SwAccess.RCLR:
            state.mirrored = 0
            state.desired = 0
        elif self.sw_access == SwAccess.RSET:
            state.mirrored = field.mask
            state.desired = field.mask

    def check_on_read(self, field: RegisterField, state: FieldState) -> bool:
        """Return True if the field should be checked on reads."""
        if field.volatile:
            return False
        return state.check_enabled and self.sw_access in (
            SwAccess.RW,
            SwAccess.W1C,
            SwAccess.W1S,
            SwAccess.RCLR,
            SwAccess.RSET,
        )


class PolicyRegistry:
    """Minimal registry from field spec to runtime policy object."""

    def policy_for(self, field: RegisterField) -> AccessPolicy:
        return AccessPolicy(field.sw_access)
