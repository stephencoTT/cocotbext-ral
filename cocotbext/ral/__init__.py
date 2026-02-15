"""Cocotb Register Abstraction Layer (RAL).

Generic, reusable RAL with zero Quasar-specific dependencies. Works with
standard cocotbext AXI/APB VIPs and generic JSON/RDL register descriptions.
"""

from .version import __version__
from .register_model import RegisterField, Register, RegisterBlock, RegisterModel, SwAccess
from .predictor import Predictor, PredictionResult, FieldResult
from .checker import Checker

# Cocotb-dependent classes — only available in simulation environments
try:
    from .monitor import ApbRalMonitor, AxiLiteRalMonitor, AxiRalMonitor
    from .ral import RAL
except ImportError:
    pass
