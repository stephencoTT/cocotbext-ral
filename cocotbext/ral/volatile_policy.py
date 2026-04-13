"""Volatile field helpers.

Volatile fields represent hardware-driven values that may change outside of
software control. Prediction checks should typically be skipped.

This module provides :func:`is_field_volatile` for use by the access-policy
and predictor layers, plus a backwards-compatible :class:`VolatileMixin` for
classes that prefer a mixin-style API.
"""

from __future__ import annotations

from .register_model import RegisterField
from .state import FieldState


def is_field_volatile(field: RegisterField) -> bool:
    """Return True if the field is volatile (hardware-driven)."""
    return getattr(field, "volatile", False)


def check_allowed(field: RegisterField, state: FieldState) -> bool:
    """Return True if the field can be prediction-checked on read."""
    if is_field_volatile(field):
        return False
    return state.check_enabled


class VolatileMixin:
    """Mixin providing volatile-aware helpers for classes that need them."""

    def is_volatile(self, field: RegisterField) -> bool:
        return is_field_volatile(field)

    def check_allowed(self, field: RegisterField, state: FieldState) -> bool:
        return check_allowed(field, state)
