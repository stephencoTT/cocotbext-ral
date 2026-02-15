"""Load a RegisterModel from SystemRDL source files.

Uses the systemrdl-compiler package to parse RDL and produce the same
RegisterModel as the JSON loader.
"""

from typing import List, Union
from pathlib import Path

from ..register_model import (
    RegisterField,
    Register,
    RegisterModel,
    SwAccess,
)


def _map_sw_access(sw_prop, woclr: bool) -> SwAccess:
    """Map systemrdl AccessType + woclr to SwAccess enum."""
    from systemrdl.rdltypes import AccessType  # type: ignore

    if sw_prop == AccessType.rw and woclr:
        return SwAccess.WOCLR
    if sw_prop == AccessType.rw:
        return SwAccess.RW
    if sw_prop == AccessType.r:
        return SwAccess.RO
    if sw_prop == AccessType.w:
        return SwAccess.WO
    return SwAccess.RW


def _walk_node(node, model: RegisterModel, name_prefix: str = ""):
    """Recursively walk the compiled RDL address map.

    Uses children(unroll=True) so array containers and array registers
    are automatically expanded into individual indexed elements.
    """
    from systemrdl.node import (  # type: ignore
        AddrmapNode,
        RegfileNode,
        RegNode,
        FieldNode,
        RootNode,
    )

    # RootNode is a wrapper — don't include it in the name hierarchy
    if isinstance(node, RootNode):
        for child in node.children(unroll=True):
            _walk_node(child, model, name_prefix)
        return

    # Build the name for this node, including array index if applicable
    inst_name = node.inst_name
    if node.is_array:
        idx = node.current_idx
        if idx is not None:
            idx_str = ",".join(str(i) for i in idx) if len(idx) > 1 else str(idx[0])
            inst_name = f"{inst_name}[{idx_str}]"

    if name_prefix:
        current_name = f"{name_prefix}.{inst_name}"
    else:
        current_name = inst_name

    if isinstance(node, RegNode):
        fields = []
        for field_node in node.fields():
            if isinstance(field_node, FieldNode):
                reset_val = field_node.get_property("reset") or 0
                if not isinstance(reset_val, int):
                    reset_val = 0
                woclr = bool(field_node.get_property("woclr"))
                sw_access = _map_sw_access(
                    field_node.get_property("sw"),
                    woclr,
                )
                field = RegisterField(
                    name=field_node.inst_name,
                    lsb=field_node.low,
                    msb=field_node.high,
                    reset_value=reset_val,
                    sw_access=sw_access,
                )
                fields.append(field)

        reg = Register(
            name=inst_name,
            address=node.absolute_address,
            size_bits=node.size * 8,
            fields=fields,
            description=node.get_property("desc") or "",
        )
        model.add_register(reg, hierarchical_name=current_name)
        return

    # Recurse into addrmaps, regfiles, and other containers
    if isinstance(node, (AddrmapNode, RegfileNode)):
        for child in node.children(unroll=True):
            _walk_node(child, model, current_name)


def load_rdl(
    rdl_path: Union[str, Path],
    top_name: str = "",
    incdir: List[str] = None,
    model_name: str = "",
) -> RegisterModel:
    """Load a RegisterModel from SystemRDL source.

    Args:
        rdl_path: Path to the .rdl file.
        top_name: Top-level addrmap name to elaborate. If empty, uses the
            root addrmap.
        incdir: List of include directories for RDL compilation.
        model_name: Optional name for the model.

    Returns:
        A populated RegisterModel.

    Raises:
        ImportError: If systemrdl-compiler is not installed.
    """
    try:
        from systemrdl import RDLCompiler  # type: ignore
    except ImportError:
        raise ImportError(
            "systemrdl-compiler is required for RDL loading. "
            "Install it with: pip install systemrdl-compiler"
        )

    rdl_path = Path(rdl_path)
    incdir = incdir or []

    rdlc = RDLCompiler()
    rdlc.compile_file(str(rdl_path), incl_search_paths=[str(d) for d in incdir])
    root = rdlc.elaborate(top_def_name=top_name or None)

    name = model_name or top_name or rdl_path.stem
    model = RegisterModel(name=name)

    _walk_node(root, model)

    return model
