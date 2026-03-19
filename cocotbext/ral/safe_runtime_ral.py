from .runtime_ral import RuntimeRAL
from .rmw_policy import assess_field_rmw


class SafeRuntimeRAL(RuntimeRAL):
    """Runtime-backed RAL with conservative read-modify-write safety checks.

    ``SafeRuntimeRAL`` extends :class:`RuntimeRAL` by validating field-level
    writes before performing a read-modify-write sequence. This prevents
    accidental corruption of neighboring fields in mixed-access registers.

    Typical cases where this matters include registers that combine:

    - read-only status bits
    - writable control bits
    - write-clear style fields
    - hardware-driven state that can change between read and write

    If a requested field write is deemed unsafe, the operation fails loudly
    instead of silently updating unrelated bits.

    Recommended for:
    - verification flows that prioritize correctness over convenience
    - CSR maps with mixed field access policies
    - debugging subtle register corruption behavior
    """

    async def write_field(self, reg_name: str, field_name: str, value: int):
        """Write a field using a conservatively checked RMW sequence.

        Args:
            reg_name: Register name.
            field_name: Target field name within the register.
            value: Field value to write.

        Raises:
            RuntimeError: If the read-modify-write update is unsafe.
        """
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
