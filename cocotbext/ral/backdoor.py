"""Backdoor path resolution helpers.

This module separates logical backdoor identifiers from concrete HDL paths so a
single register spec can be reused across multiple DUT integration contexts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .register_model import Register, RegisterField


class BackdoorResolver:
    """Resolve logical or explicit backdoor references to concrete HDL paths."""

    def resolve_register_path(self, register: Register) -> Optional[str]:
        if register.hdl_path:
            return register.hdl_path
        return None

    def resolve_field_path(self, register: Register, field: RegisterField) -> Optional[str]:
        if field.hdl_path:
            return field.hdl_path
        return None


@dataclass
class MappingBackdoorResolver(BackdoorResolver):
    """Resolver backed by explicit name-to-path maps.

    Keys are hierarchical register names and hierarchical field names of the
    form ``reg_hname.field_name``.
    """

    register_paths: Dict[str, str]
    field_paths: Dict[str, str]

    def resolve_register_path(self, register: Register) -> Optional[str]:
        return self.register_paths.get(register.hierarchical_name, super().resolve_register_path(register))

    def resolve_field_path(self, register: Register, field: RegisterField) -> Optional[str]:
        key = f"{register.hierarchical_name}.{field.name}"
        return self.field_paths.get(key, super().resolve_field_path(register, field))


@dataclass
class PrefixBackdoorResolver(BackdoorResolver):
    """Resolver that prefixes relative spec paths with a runtime instance root."""

    prefix: str

    def _join(self, suffix: str) -> str:
        if not suffix:
            return suffix
        if suffix.startswith(self.prefix):
            return suffix
        return f"{self.prefix}.{suffix}" if self.prefix else suffix

    def resolve_register_path(self, register: Register) -> Optional[str]:
        path = super().resolve_register_path(register)
        return self._join(path) if path else None

    def resolve_field_path(self, register: Register, field: RegisterField) -> Optional[str]:
        path = super().resolve_field_path(register, field)
        return self._join(path) if path else None
