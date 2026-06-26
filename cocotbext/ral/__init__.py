"""Cocotb Register Abstraction Layer (RAL).

Generic, reusable RAL with zero project-specific dependencies.
"""

from .version import __version__
from .register_model import RegisterField, Register, RegisterBlock, RegisterModel, SwAccess, Memory
from .runtime_predictor import RuntimePredictor, PredictionResult, FieldResult
from .state import RuntimeState, RegisterState, FieldState
from .checker import Checker

# Runtime-backed RAL API.
from .runtime_ral import RuntimeRAL
from .transaction_logger import TransactionLogger

# Cocotb-dependent classes (optional: only importable when cocotb is present).
try:
    from .monitor import ApbRalMonitor, AxiLiteRalMonitor, AxiRalMonitor  # noqa: F401
except ImportError:
    pass

__all__ = [
    "__version__",
    # Core model
    "RegisterField", "Register", "RegisterBlock", "RegisterModel", "SwAccess", "Memory",
    # Prediction / checking
    "RuntimePredictor", "PredictionResult", "FieldResult", "Checker",
    # Runtime state
    "RuntimeState", "RegisterState", "FieldState",
    # Runtime-backed RAL
    "RuntimeRAL", "TransactionLogger",
]
