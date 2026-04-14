"""Cocotb Register Abstraction Layer (RAL).

Generic, reusable RAL with zero Quasar-specific dependencies.
"""

from .version import __version__
from .register_model import RegisterField, Register, RegisterBlock, RegisterModel, SwAccess
from .predictor import Predictor, PredictionResult, FieldResult
from .checker import Checker

# Runtime-backed APIs (recommended)
from .integrated_runtime_ral import IntegratedRuntimeRAL
from .runtime_ral import RuntimeRAL
from .safe_runtime_ral import SafeRuntimeRAL
from .transaction_logger import TransactionLogger

# Cocotb-dependent classes
try:
    from .monitor import ApbRalMonitor, AxiLiteRalMonitor, AxiRalMonitor
    from .ral import RAL
except ImportError:
    pass
