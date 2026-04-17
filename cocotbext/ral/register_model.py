"""Register data model for the cocotb RAL.

Pure Python — no cocotb dependency. Defines the hierarchical register model
consisting of fields, registers, register blocks, and a top-level model.
"""

import fnmatch
import re as _re
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


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

    # Access types that are inherently volatile (hardware-driven, not software-predictable).
    _VOLATILE_ACCESS_TYPES = frozenset({SwAccess.RO, SwAccess.RCLR, SwAccess.RSET})

    def __init__(
        self,
        name: str,
        lsb: int,
        msb: int,
        reset_value: int = 0,
        sw_access: SwAccess = SwAccess.RW,
        hdl_path: str = "",
        volatile: Optional[bool] = None,
    ):
        self.name = name
        self.lsb = lsb
        self.msb = msb
        self.width = msb - lsb + 1
        self.mask = (1 << self.width) - 1
        self.reset_value = reset_value & self.mask
        self.sw_access = sw_access
        self.hdl_path = hdl_path
        # If volatile is not explicitly set, infer from access type.
        if volatile is None:
            self.volatile = sw_access in self._VOLATILE_ACCESS_TYPES
        else:
            self.volatile = volatile

    # Access types whose mirror can be prediction-checked on reads. The
    # runtime layer additionally gates checks on RuntimeState.check_enabled
    # and the field's volatile flag.
    _CHECKABLE_ACCESS_TYPES = frozenset({
        SwAccess.RW, SwAccess.W1C, SwAccess.W1S,
        SwAccess.RCLR, SwAccess.RSET,
    })

    @property
    def is_checkable_on_read(self) -> bool:
        """Spec-level predicate: is this field eligible for read-check?

        True iff the access type allows prediction *and* the field is not
        volatile. The runtime layer additionally consults
        :attr:`FieldState.check_enabled` before actually comparing.
        """
        if self.volatile:
            return False
        return self.sw_access in self._CHECKABLE_ACCESS_TYPES

    @property
    def is_writable(self) -> bool:
        """True if software can write to this field."""
        return self.sw_access in (SwAccess.RW, SwAccess.WO, SwAccess.W1C, SwAccess.W1S)

    @property
    def is_volatile(self) -> bool:
        """True if the field is marked as volatile / hardware-driven."""
        return self.volatile

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

    # ------------------------------------------------------------------
    # Search / grouping helpers
    # ------------------------------------------------------------------

    def find_registers(
        self,
        name: Optional[str] = None,
        *,
        regex: Optional[str] = None,
        access: Optional[SwAccess] = None,
        hierarchy_prefix: Optional[str] = None,
        predicate: Optional[Callable[["Register"], bool]] = None,
    ) -> List["Register"]:
        """Return registers matching all supplied criteria, sorted by address.

        Args:
            name: fnmatch-style glob against the register's hierarchical name
                (e.g. ``"DMA*.CTRL"``). Mutually exclusive with ``regex``.
            regex: Regular expression matched against the hierarchical name
                via ``re.search``. Mutually exclusive with ``name``.
            access: If given, only registers with at least one field whose
                ``sw_access`` matches are returned.
            hierarchy_prefix: Restrict search to a subtree; matches
                hierarchical names equal to ``prefix`` or starting with
                ``prefix + "."``.
            predicate: Optional arbitrary filter callable receiving a
                :class:`Register` and returning ``bool``.

        Returns:
            List of registers sorted by ascending address.
        """
        if name is not None and regex is not None:
            raise ValueError("Pass either name= or regex=, not both")

        name_matcher: Optional[Callable[[str], bool]] = None
        if name is not None:
            name_matcher = lambda s, p=name: fnmatch.fnmatchcase(s, p)
        elif regex is not None:
            compiled = _re.compile(regex)
            name_matcher = lambda s, r=compiled: r.search(s) is not None

        def _matches(reg: "Register") -> bool:
            if name_matcher is not None and not name_matcher(reg.hierarchical_name):
                return False
            if hierarchy_prefix is not None:
                if not (reg.hierarchical_name == hierarchy_prefix
                        or reg.hierarchical_name.startswith(hierarchy_prefix + ".")):
                    return False
            if access is not None:
                if not any(f.sw_access == access for f in reg.fields):
                    return False
            if predicate is not None and not predicate(reg):
                return False
            return True

        results = [reg for reg in self._by_address.values() if _matches(reg)]
        results.sort(key=lambda r: r.address)
        return results

    def find_fields(
        self,
        name: Optional[str] = None,
        *,
        regex: Optional[str] = None,
        access: Optional[SwAccess] = None,
        reg_name: Optional[str] = None,
        hierarchy_prefix: Optional[str] = None,
        predicate: Optional[Callable[["Register", "RegisterField"], bool]] = None,
    ) -> List[Tuple["Register", "RegisterField"]]:
        """Return (register, field) pairs matching all supplied criteria.

        Args:
            name: fnmatch glob against the field name.
            regex: Regex against the field name (mutually exclusive with
                ``name``).
            access: Filter fields by ``sw_access``.
            reg_name: fnmatch glob against the owning register's
                hierarchical name.
            hierarchy_prefix: Restrict to registers under a subtree.
            predicate: Arbitrary ``(reg, field) -> bool`` filter.

        Returns:
            Sorted by ``(register.address, field.lsb)``.
        """
        if name is not None and regex is not None:
            raise ValueError("Pass either name= or regex=, not both")

        reg_candidates = self.find_registers(
            name=reg_name, hierarchy_prefix=hierarchy_prefix,
        )

        field_matcher: Optional[Callable[[str], bool]] = None
        if name is not None:
            field_matcher = lambda s, p=name: fnmatch.fnmatchcase(s, p)
        elif regex is not None:
            compiled = _re.compile(regex)
            field_matcher = lambda s, r=compiled: r.search(s) is not None

        results: List[Tuple[Register, RegisterField]] = []
        for reg in reg_candidates:
            for f in reg.fields:
                if field_matcher is not None and not field_matcher(f.name):
                    continue
                if access is not None and f.sw_access != access:
                    continue
                if predicate is not None and not predicate(reg, f):
                    continue
                results.append((reg, f))
        results.sort(key=lambda rf: (rf[0].address, rf[1].lsb))
        return results

    def group_by(
        self,
        key: Callable[["Register"], Any],
    ) -> Dict[Any, List["Register"]]:
        """Group registers by an arbitrary key function.

        Typical use is to fold instance-indexed hierarchies into a dict
        keyed by instance label, e.g.::

            by_engine = model.group_by(
                lambda r: r.hierarchical_name.split(".")[0]
            )
            # {"DMA0": [...], "DMA1": [...], ...}

        Values are address-sorted within each group.
        """
        groups: Dict[Any, List[Register]] = {}
        for reg in sorted(self._by_address.values(), key=lambda r: r.address):
            groups.setdefault(key(reg), []).append(reg)
        return groups

    def summary(self) -> str:
        lines = [f"RegisterModel: {self.name!r} ({self.register_count} registers)"]
        for addr in sorted(self._by_address):
            reg = self._by_address[addr]
            lines.append(f"  0x{addr:08x}: {reg.name} ({len(reg.fields)} fields)")
        return "\n".join(lines)

    def __repr__(self):
        return f"RegisterModel({self.name!r}, {self.register_count} regs)"
