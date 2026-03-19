from typing import Union

from .runtime_ral import RuntimeRAL
from .rmw_policy import assess_field_rmw


class SafeRuntimeRAL(RuntimeRAL):
    """RuntimeRAL variant with conservative RMW protection.

    This overrides write_field() to avoid unsafe read-modify-write sequences.
    """

    async def write_field(self, reg_name: str, field_name: str, value: int):
        reg = self.get_register(reg_name)

        assessment = assess_field_rmw(reg, field_name)
        if not assessment.safe:
            reasons = "; ".join(assessment.reasons)
            raise RuntimeError(
                f"Unsafe RMW on {reg.hierarchical_name}.{field_name}: {reasons}"
            )

        current = await self.read(reg.address)
        field = reg.get_field(field_name)
        mask = field.mask << field.lsb
        new_value = (current & ~mask) | ((value & field.mask) << field.lsb)

        await self.write(reg.address, new_value)
