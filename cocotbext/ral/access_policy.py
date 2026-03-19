"""Field access policy helpers for the runtime path.

Extended to support common SystemRDL semantics such as W1C, W1S, RCLR, and RSET.
"""

from dataclasses import dataclass

from .register_model import RegisterField, SwAccess
from .state import FieldState


@dataclass(frozen=True)
class AccessPolicy:
    sw_access: SwAccess

    def apply_write(self, field: RegisterField, state: FieldState, write_value: int) -> None:
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

        elif self.sw_access == SwAccess.RO:
            return

        state.desired = state.mirrored
        state.dirty = False

    def apply_read_side_effect(self, field: RegisterField, state: FieldState) -> None:
        if self.sw_access == SwAccess.RCLR:
            state.mirrored = 0
        elif self.sw_access == SwAccess.RSET:
            state.mirrored = field.mask

    def check_on_read(self, state: FieldState) -> bool:
        return state.check_enabled


class PolicyRegistry:
    def policy_for(self, field: RegisterField) -> AccessPolicy:
        return AccessPolicy(field.sw_access)
