"""Volatile field helpers.

Volatile fields represent hardware-driven values that may change outside of
software control. Prediction checks should typically be skipped.
"""

from __future__ import annotations

from .state import FieldState


class VolatileMixin:
    def is_volatile(self, field) -> bool:
        return getattr(field, "volatile", False)

    def check_allowed(self, field, state: FieldState) -> bool:
        if self.is_volatile(field):
            return False
        return state.check_enabled
