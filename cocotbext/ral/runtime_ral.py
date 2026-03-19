from typing import Union

from .ral import RAL
from .runtime_predictor import RuntimePredictor
from .state import RuntimeState


class RuntimeRAL(RAL):
    """Runtime-backed Register Abstraction Layer.

    ``RuntimeRAL`` keeps the familiar cocotb-facing RAL API while replacing
    the legacy predictor path with a runtime-state-based engine.

    Compared to the legacy ``RAL`` class, this implementation introduces a
    clean separation between:

    - structural register specification data stored in ``RegisterModel``
    - mutable mirrored / desired / checking state stored in ``RuntimeState``

    This makes the model easier to extend and safer to reuse across multiple
    instances of the same block.

    Recommended for:
    - new cocotb verification environments
    - designs with repeated IP instances
    - flows that need runtime introspection or custom policy extensions
    """

    def __init__(self, name, model, dut_handle=None):
        """Create a runtime-backed RAL instance.

        Args:
            name: Human-readable instance name used in logs.
            model: Register specification model.
            dut_handle: Optional cocotb DUT handle for backdoor access.
        """
        super().__init__(name, model, dut_handle)
        self.runtime_state = RuntimeState(model)
        self._predictor = RuntimePredictor(model, runtime_state=self.runtime_state, logger_name=f"ral.{name}")

    def disable_check(self, name_or_addr: Union[str, int], field_name: str = ""):
        """Disable prediction checking for a register or field in runtime state."""
        self.runtime_state.disable_check(name_or_addr, field_name)

    def enable_check(self, name_or_addr: Union[str, int], field_name: str = ""):
        """Enable prediction checking for a register or field in runtime state."""
        self.runtime_state.enable_check(name_or_addr, field_name)

    def set_predicted(self, name_or_addr: Union[str, int], value: int):
        """Set the mirrored value for every field in a register."""
        reg = self.get_register(name_or_addr)
        for f in reg.fields:
            self.runtime_state.set_field_mirrored(reg.address, f.name, (value >> f.lsb) & f.mask)

    def set_field_predicted(self, reg_name: str, field_name: str, value: int):
        """Set the mirrored value for a single field."""
        reg = self.get_register(reg_name)
        self.runtime_state.set_field_mirrored(reg.address, field_name, value)
