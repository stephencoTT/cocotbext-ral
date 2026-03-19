"""Helpers for assessing read-modify-write safety.

A plain register read followed by a full-register write is not universally safe.
This module provides a conservative policy that higher-level RAL helpers can use
before performing field writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .register_model import Register, SwAccess


@dataclass
class RmwAssessment:
    safe: bool
    reasons: List[str] = field(default_factory=list)


def assess_field_rmw(register: Register, field_name: str) -> RmwAssessment:
    """Conservatively assess whether a field write can use RMW safely.

    Current policy intentionally errs on the side of blocking RMW unless all
    non-target fields are plain RW. This avoids silent corruption for common CSR
    patterns such as status/RO bits, write-only command bits, and write-clear
    fields.
    """
    target = register.get_field(field_name)
    if target is None:
        return RmwAssessment(False, [f"field {field_name!r} not found in {register.name}"])

    reasons: List[str] = []

    if not target.is_writable:
        reasons.append(
            f"target field {register.hierarchical_name}.{target.name} is not writable"
        )

    if target.sw_access not in (SwAccess.RW, SwAccess.WOCLR, SwAccess.WO):
        reasons.append(
            f"target field {register.hierarchical_name}.{target.name} has unsupported access {target.sw_access.name}"
        )

    for field in register.fields:
        if field.name == field_name:
            continue
        if field.sw_access != SwAccess.RW:
            reasons.append(
                f"neighbor field {register.hierarchical_name}.{field.name} has access {field.sw_access.name}"
            )

    return RmwAssessment(safe=len(reasons) == 0, reasons=reasons)
