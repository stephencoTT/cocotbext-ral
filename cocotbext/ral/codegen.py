"""Code generation utilities for cocotbext-ral.

Generates Python namespace modules from a ``RegisterModel`` so that
register paths can be auto-completed by IDEs and statically checked
by type checkers.

Usage::

    from cocotbext.ral.adapters import load_json
    from cocotbext.ral.codegen import generate_namespace

    model = load_json("registers.json")
    generate_namespace(model, "output/mychip_ns.py")

The generated module provides a nested class hierarchy that mirrors
the register model's hierarchical names. Each leaf attribute is a
string constant equal to the full model path::

    from output.mychip_ns import mychip

    mychip.cpu.reset_unit.SS_CONFIG
    # == "mychip.cpu.reset_unit.SS_CONFIG"
"""

from __future__ import annotations

import keyword
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from .register_model import RegisterModel


def _sanitize(name: str) -> str:
    """Make a name safe for use as a Python identifier."""
    # Replace characters invalid in identifiers
    name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    # Ensure it doesn't start with a digit
    if name and name[0].isdigit():
        name = f"_{name}"
    # Avoid Python keywords
    if keyword.iskeyword(name):
        name = f"{name}_"
    return name


def generate_namespace(
    model: RegisterModel,
    output_path: Union[str, Path],
    root_class: Optional[str] = None,
    include_memories: bool = True,
) -> None:
    """Generate a Python namespace module from a register model.

    The output file contains nested classes where each leaf attribute
    is a string constant equal to the register's hierarchical name in
    the model. IDEs can auto-complete at every dot level.

    Args:
        model: The register model to generate from.
        output_path: Path to write the generated Python file.
        root_class: Name for the top-level class. Defaults to the
            model name.
        include_memories: If True, include memory region constants.
    """
    output_path = Path(output_path)
    root_name = root_class or model.name or "regs"
    root_name = _sanitize(root_name)

    # Build a tree structure from hierarchical names.
    # Strip the root prefix (model name) from paths so the tree starts
    # at the first level below root, matching the class hierarchy.
    tree: Dict = {}

    def _insert(hierarchical_name: str) -> None:
        parts = hierarchical_name.split(".")
        # Skip the root level if it matches root_name (avoid doubling)
        if parts and _sanitize(parts[0]) == root_name:
            parts = parts[1:]
        node = tree
        for part in parts[:-1]:
            safe = _sanitize(part)
            if safe not in node:
                node[safe] = {}
            elif not isinstance(node[safe], dict):
                # Name collision: a register and a block share a name.
                # The block (dict) takes priority; register becomes a
                # child with a _REG suffix.
                node[safe] = {}
            node = node[safe]
        if parts:
            leaf = _sanitize(parts[-1])
            if leaf not in node or not isinstance(node.get(leaf), dict):
                node[leaf] = hierarchical_name

    for reg in model.all_registers():
        _insert(reg.hierarchical_name)

    if include_memories:
        for mem in model.all_memories():
            _insert(mem.hierarchical_name)

    # Generate Python source
    lines: List[str] = []
    lines.append(f'"""Auto-generated register namespace from model {model.name!r}.')
    lines.append("")
    lines.append("Do not edit manually. Regenerate from the register model.")
    lines.append('"""')
    lines.append("")
    lines.append("")

    # Collect all classes we need to generate (bottom-up)
    classes: List[Tuple[str, str, Dict]] = []  # (class_name, path_prefix, children)
    _collect_classes(tree, root_name, "", classes)

    # Emit classes bottom-up so inner classes are defined before outer ones reference them
    for class_name, path_prefix, children in classes:
        _emit_class(lines, class_name, children)
        lines.append("")

    # Emit root instance
    lines.append("# Root namespace instance — import this")
    lines.append(f"{root_name} = _{root_name}()")
    lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines))


def _collect_classes(
    node: Dict,
    class_name: str,
    path_prefix: str,
    result: List[Tuple[str, str, Dict]],
) -> None:
    """Recursively collect class definitions bottom-up."""
    children_info: Dict = {}

    for key, value in sorted(node.items()):
        if isinstance(value, dict):
            # Sub-namespace — recurse
            child_class = f"_{class_name}_{key}"
            child_path = f"{path_prefix}.{key}" if path_prefix else key
            _collect_classes(value, f"{class_name}_{key}", child_path, result)
            children_info[key] = ("class", child_class)
        else:
            # Leaf — string constant
            children_info[key] = ("const", value)

    result.append((f"_{class_name}", path_prefix, children_info))


def _emit_class(lines: List[str], class_name: str, children: Dict) -> None:
    """Emit a single class definition."""
    lines.append(f"class {class_name}:")

    has_content = False
    # Emit constants first
    for key, (kind, value) in sorted(children.items()):
        if kind == "const":
            lines.append(f"    {key} = {value!r}")
            has_content = True

    # Emit sub-namespace instances
    for key, (kind, value) in sorted(children.items()):
        if kind == "class":
            lines.append(f"    {key} = {value}()")
            has_content = True

    if not has_content:
        lines.append("    pass")
