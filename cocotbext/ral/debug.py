"""Debug and introspection helpers for runtime RAL."""

from __future__ import annotations

from typing import List

from .state import RuntimeState


def dump_state(runtime: RuntimeState) -> str:
    lines: List[str] = []
    for addr, reg_state in runtime._registers.items():
        lines.append(f"0x{addr:08x}:")
        for fname, fstate in reg_state.fields.items():
            lines.append(
                f"  {fname}: mirrored=0x{fstate.mirrored:x} desired=0x{fstate.desired:x} check={fstate.check_enabled}"
            )
    return "\n".join(lines)


def diff_state(runtime: RuntimeState, actual: int, address: int) -> str:
    reg_state = runtime._registers.get(address)
    if not reg_state:
        return "<no state>"

    lines: List[str] = []
    for fname, fstate in reg_state.fields.items():
        lines.append(
            f"{fname}: expected=0x{fstate.mirrored:x}"
        )
    lines.append(f"actual=0x{actual:x}")
    return "\n".join(lines)
