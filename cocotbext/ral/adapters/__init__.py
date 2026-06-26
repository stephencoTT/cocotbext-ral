from .json_loader import load_json  # noqa: F401

try:
    from .rdl_loader import load_rdl  # noqa: F401
except ImportError:
    pass

__all__ = ["load_json", "load_rdl"]
