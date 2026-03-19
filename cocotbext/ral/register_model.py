"""Register data model for the cocotb RAL.

Pure Python — no cocotb dependency. Defines the hierarchical register model
consisting of fields, registers, register blocks, and a top-level model.
"""

from enum import Enum
from typing import Dict, List, Optional, Union


class SwAccess(Enum):
    """Software-visible access policy for a field.

    Canonical values:
    - RW
    - RO
    - WO
    - W1C
    - W1S
    - RCLR
    - RSET

    Compatibility aliases:
    - WOCLR -> W1C
    - WOSET -> W1S
    - RC -> RCLR
    - RS -> RSET
    """

    RW = "rw"
    RO = "ro"
    WO = "wo"
    W1C = "w1c"
    WOCLR = "w1c"
    W1S = "w1s"
    WOSET = "w1s"
    RCLR = "rclr"
    RC = "rclr"
    RSET = "rset"
    RS = "rset"


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
        volatile: bool = False,
    ):
        self.name = name
        self.lsb = lsb
        self.msb = msb
        self.width = msb - lsb + 1
        self.mask = (1 << self.width) - 1
        self.reset_value = reset_value & self.mask
        self.sw_access = sw_access
        self.hdl_path = hdl_path
        self.volatile = volatile
        self.predicted_value = self.reset_value
        self.check_enabled = True

    @property
    def is_checkable_on_read(self) -> bool:
        """True if the field's predicted value can be checked on a read."""
        if self.volatile:
            return False
        return self.check_enabled and self.sw_access in (
            SwAccess.RW,
            SwAccess.W1C,
            SwAccess.W1S,
            SwAccess.RCLR,
            SwAccess.RSET,
        )

    @property
    def is_writable(self) -> bool:
        """True if software can write to this field."""
        return self.sw_access in (SwAccess.RW, SwAccess.WO, SwAccess.W1C, SwAccess.W1S)

    @property
    def is_volatile(self) -> bool:
        """True if the field is marked as volatile / hardware-driven."""
        return self.volatile

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
        self.hierarchical_name = name

    @property
    def size_bytes(self) -> int:
        return self.size_bits // 8

    @property
    def predicted_value(self) -> int:
        value = 0
        for f in self.fields:
            value |= (f.predicted_value & f.mask) << f.lsb
        return value

    @property
    def reset_value(self) -> int:
        value = 0
        for f in self.fields:
            value |= (f.reset_value & f.mask) << f.lsb
        return value

    @property
    def has_backdoor(self) -> bool:
        if self.hdl_path:
            return True
        return any(f.hdl_path for f in self.fields)

    def get_field(self, name: str) -> Optional[RegisterField]:
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def get_writable_mask(self) -> int:
        mask = 0
        for f in self.fields:
            if f.is_writable:
                mask |= f.mask << f.lsb
        return mask

    def get_checkable_mask(self) -> int:
        mask = 0
        for f in self.fields:
            if f.is_checkable_on_read:
                mask |= f.mask << f.lsb
        return mask

    def reset(self):
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
        self._by_address[reg.address] = reg
        name_key = hierarchical_name or reg.name
        reg.hierarchical_name = name_key
        self._by_name[name_key] = reg
        leaf_name = name_key.rsplit(".", 1)[-1] if "." in name_key else name_key
        if leaf_name not in self._by_name:
            self._by_name[leaf_name] = reg

    def get_register(self, name_or_addr: Union[str, int]) -> Optional[Register]:
        if isinstance(name_or_addr, int):
            return self._by_address.get(name_or_addr)
        if name_or_addr in self._by_name:
            return self._by_name[name_or_addr]
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
        return list(self._by_address.values())

    def reset(self):
        for reg in self._by_address.values():
            reg.reset()

    def summary(self) -> str:
        lines = [f"RegisterModel: {self.name!r} ({self.register_count} registers)"]
        for addr in sorted(self._by_address):
            reg = self._by_address[addr]
            lines.append(f"  0x{addr:08x}: {reg.name} ({len(reg.fields)} fields)")
        return "\n".join(lines)

    def __repr__(self):
        return f"RegisterModel({self.name!r}, {self.register_count} regs)"
