from .json_loader import load_json

try:
    from .rdl_loader import load_rdl
except ImportError:
    pass
