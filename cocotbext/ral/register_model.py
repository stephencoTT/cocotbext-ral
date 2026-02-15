"""Register data model for the cocotb RAL.

Pure Python — no cocotb dependency. Defines the hierarchical register model
consisting of fields, registers, register blocks, and a top-level model.
"""

from enum import Enum, auto
from typing import Dict, List, Optional, Union


class SwAccess(Enum):
    """Software access type for register fields."""
    RW = auto()
    RO = auto()
    WO = auto()
    WOCLR = auto()


class RegisterField:
    """A single bit-field within a register."""

    def __init__(
        self,
        name: str,
        lsb: int,
        msb: int,
        reset_value: int = 0,
        sw_access: SwAccess = SwAccess.RW,
        hdl_path: str = "",
    ):
        self.name = name
        self.lsb = lsb
        self.msb = msb
        self.width = msb - lsb + 1
        self.mask = (1 << self.width) - 1
        self.reset_value = reset_value & self.mask
        self.sw_access = sw_access
        self.hdl_path = hdl_path
        self.predicted_value = self.reset_value
        self.check_enabled = True

    @property
    def is_checkable_on_read(self) -> bool:
        """True if the field's predicted value can be checked on a read."""
        return self.check_enabled and self.sw_access in (SwAccess.RW, SwAccess.WOCLR)

    @property
    def is_writable(self) -> bool:
        """True if software can write to this field."""
        return self.sw_access in (SwAccess.RW, SwAccess.WO, SwAccess.WOCLR)

    @property
    def is_volatile(self) -> bool:
        """True if the field is hardware-driven and unpredictable."""
        return self.sw_access == SwAccess.RO

    def reset(self):
        """Restore predicted value to the reset default."""
        self.predicted_value = self.reset_value

    def __repr__(self):
        return (
            f"RegisterField({self.name!r}, [{self.msb}:{self.lsb}], "
            f"access={self.sw_access.name}, reset=0x{self.reset_value:x})"
        )


class Register:
    """A register containing one or more bit-fields."""

    def __init__(
        self,
        name: str,
        address: int,
        size_bits: int = 32,
        fields: Optional[List[RegisterField]] = None,
        description: str = "",
        hdl_path: str = "",
    ):
        self.name = name
        self.address = address
        self.size_bits = size_bits
        self.fields: List[RegisterField] = fields or []
        self.description = description
        self.hdl_path = hdl_path
        self.hierarchical_name = name  # overwritten by RegisterModel.add_register()

    @property
    def size_bytes(self) -> int:
        return self.size_bits // 8

    @property
    def predicted_value(self) -> int:
        """Composite predicted value from all fields."""
        value = 0
        for f in self.fields:
            value |= (f.predicted_value & f.mask) << f.lsb
        return value

    @property
    def reset_value(self) -> int:
        """Composite reset value from all fields."""
        value = 0
        for f in self.fields:
            value |= (f.reset_value & f.mask) << f.lsb
        return value

    @property
    def has_backdoor(self) -> bool:
        """True if a backdoor HDL path is set on the register or any field."""
        if self.hdl_path:
            return True
        return any(f.hdl_path for f in self.fields)

    def get_field(self, name: str) -> Optional[RegisterField]:
        """Look up a field by name."""
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def get_writable_mask(self) -> int:
        """Bitmask of all writable bit positions."""
        mask = 0
        for f in self.fields:
            if f.is_writable:
                mask |= f.mask << f.lsb
        return mask

    def get_checkable_mask(self) -> int:
        """Bitmask of all checkable-on-read bit positions."""
        mask = 0
        for f in self.fields:
            if f.is_checkable_on_read:
                mask |= f.mask << f.lsb
        return mask

    def reset(self):
        """Restore all field predictions to reset values."""
        for f in self.fields:
            f.reset()

    def __repr__(self):
        return (
            f"Register({self.name!r}, addr=0x{self.address:08x}, "
            f"{self.size_bits}b, {len(self.fields)} fields)"
        )


class RegisterBlock:
    """A named group of registers sharing a base address."""

    def __init__(self, name: str, base_address: int = 0):
        self.name = name
        self.base_address = base_address
        self.registers: Dict[int, Register] = {}

    def add_register(self, reg: Register):
        self.registers[reg.address] = reg

    def reset(self):
        for reg in self.registers.values():
            reg.reset()

    def __repr__(self):
        return (
            f"RegisterBlock({self.name!r}, base=0x{self.base_address:08x}, "
            f"{len(self.registers)} regs)"
        )


class RegisterModel:
    """Top-level register model with address and name indexing."""

    def __init__(self, name: str = ""):
        self.name = name
        self._by_address: Dict[int, Register] = {}
        self._by_name: Dict[str, Register] = {}
        self.blocks: List[RegisterBlock] = []

    @property
    def register_count(self) -> int:
        return len(self._by_address)

    def add_register(self, reg: Register, hierarchical_name: str = ""):
        """Add a register to the model.

        Args:
            reg: The Register object.
            hierarchical_name: Dot-separated name for name-based lookup.
                If empty, uses reg.name.
        """
        self._by_address[reg.address] = reg
        name_key = hierarchical_name or reg.name
        # Store the full hierarchical name on the register for logging
        reg.hierarchical_name = name_key
        self._by_name[name_key] = reg
        # Also index by the leaf register name for convenience
        leaf_name = name_key.rsplit(".", 1)[-1] if "." in name_key else name_key
        if leaf_name not in self._by_name:
            self._by_name[leaf_name] = reg

    def get_register(self, name_or_addr: Union[str, int]) -> Optional[Register]:
        """Look up a register by hierarchical name or address.

        For string lookups, tries exact match first, then searches for a
        suffix match (so you can use just the register name if unambiguous).
        """
        if isinstance(name_or_addr, int):
            return self._by_address.get(name_or_addr)
        # Exact match
        if name_or_addr in self._by_name:
            return self._by_name[name_or_addr]
        # Suffix match: find names ending with the query
        matches = [
            reg for key, reg in self._by_name.items()
            if key.endswith(f".{name_or_addr}") or key == name_or_addr
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def get_register_by_address(self, address: int) -> Optional[Register]:
        return self._by_address.get(address)

    def all_registers(self) -> List[Register]:
        """Return all registers (deduplicated, since name index may have aliases)."""
        return list(self._by_address.values())

    def reset(self):
        """Restore all register predictions to reset values."""
        for reg in self._by_address.values():
            reg.reset()

    def summary(self) -> str:
        """Human-readable model summary."""
        lines = [f"RegisterModel: {self.name!r} ({self.register_count} registers)"]
        for addr in sorted(self._by_address):
            reg = self._by_address[addr]
            lines.append(f"  0x{addr:08x}: {reg.name} ({len(reg.fields)} fields)")
        return "\n".join(lines)

    def __repr__(self):
        return f"RegisterModel({self.name!r}, {self.register_count} regs)"
