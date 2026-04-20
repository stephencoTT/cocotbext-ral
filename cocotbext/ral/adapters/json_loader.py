"""Load a RegisterModel from RDL-generated JSON.

Parses the hierarchical JSON format produced by create_reg_json.py
(addrmap -> regfile -> reg -> field) into the RAL RegisterModel.
"""

import json
from typing import Union
from pathlib import Path

from ..register_model import (
    Memory,
    RegisterField,
    Register,
    RegisterBlock,
    RegisterModel,
    SwAccess,
)


def _map_sw_access(sw_access_str: str, woclr: int) -> SwAccess:
    """Map JSON sw_access string + woclr flag to SwAccess enum."""
    sw = sw_access_str.lower()
    if sw == "rw" and woclr:
        return SwAccess.WOCLR
    if sw == "rw":
        return SwAccess.RW
    if sw == "r":
        return SwAccess.RO
    if sw == "w":
        return SwAccess.WO
    # Default to RW for unknown access types
    return SwAccess.RW


def _parse_node(
    node: dict,
    model: RegisterModel,
    base_address: int,
    name_prefix: str,
):
    """Recursively walk the JSON hierarchy, accumulating addresses and names."""
    node_type = node.get("type", "")
    inst_name = node.get("inst_name", "")
    addr_offset = node.get("addr_offset", 0)
    current_address = base_address + addr_offset

    # Build hierarchical name
    if name_prefix:
        current_name = f"{name_prefix}.{inst_name}"
    else:
        current_name = inst_name

    if node_type == "reg":
        # Parse fields
        fields = []
        for child in node.get("children", []):
            if child.get("type") == "field":
                reset_val = child.get("reset", 0)
                if not isinstance(reset_val, (int, float)):
                    reset_val = 0
                reset_val = int(reset_val)

                sw_access = _map_sw_access(
                    child.get("sw_access", "rw"),
                    child.get("woclr", 0),
                )
                field = RegisterField(
                    name=child["inst_name"],
                    lsb=child["lsb"],
                    msb=child["msb"],
                    reset_value=reset_val,
                    sw_access=sw_access,
                )
                fields.append(field)

        reg = Register(
            name=inst_name,
            address=current_address,
            size_bits=node.get("regsize", 32),
            fields=fields,
            description=node.get("desc", ""),
        )
        model.add_register(reg, hierarchical_name=current_name)
        return

    if node_type == "mem":
        # Parse memory regions (SRAM, apertures, FIFOs, etc.)
        memwidth = node.get("memwidth", 32)
        mementries = node.get("mementries", 0)
        size_bytes = (memwidth * mementries) // 8
        mem = Memory(
            name=inst_name,
            base_address=current_address,
            size_bytes=size_bytes,
            description=node.get("desc", ""),
        )
        mem.hierarchical_name = current_name
        model.add_memory(mem, hierarchical_name=current_name)
        return

    # For addrmap, regfile, or any container: recurse into children
    for child in node.get("children", []):
        child_type = child.get("type", "")
        if child_type in ("addrmap", "regfile", "reg", "mem"):
            _parse_node(child, model, current_address, current_name)


def load_json(
    json_path: Union[str, Path],
    model_name: str = "",
) -> RegisterModel:
    """Load a RegisterModel from an RDL-generated JSON file.

    Args:
        json_path: Path to the JSON register description file.
        model_name: Optional name for the model. Defaults to the root
            inst_name from the JSON.

    Returns:
        A populated RegisterModel.
    """
    json_path = Path(json_path)
    with open(json_path, "r") as f:
        root = json.load(f)

    name = model_name or root.get("inst_name", json_path.stem)
    model = RegisterModel(name=name)

    # The root is typically an addrmap — recurse from there
    _parse_node(root, model, base_address=0, name_prefix="")

    return model
