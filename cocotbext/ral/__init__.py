"""Cocotb Register Abstraction Layer (RAL).

Generic, reusable RAL with zero Quasar-specific dependencies.
"""

from .version import __version__
from .register_model import RegisterField, Register, RegisterBlock, RegisterModel, SwAccess
from .runtime_predictor import RuntimePredictor, PredictionResult, FieldResult
from .state import RuntimeState, RegisterState, FieldState
from .checker import Checker

# Runtime-backed RAL APIs.
from .runtime_ral import RuntimeRAL
from .safe_runtime_ral import SafeRuntimeRAL
from .integrated_runtime_ral import IntegratedRuntimeRAL
from .transaction_logger import TransactionLogger

# Cocotb-dependent classes.
try:
    from .monitor import ApbRalMonitor, AxiLiteRalMonitor, AxiRalMonitor
except ImportError:
    pass
