from typing import Union

from .ral import RAL
from .runtime_predictor import RuntimePredictor
from .state import RuntimeState


class RuntimeRAL(RAL):
    def __init__(self, name, model, dut_handle=None):
        super().__init__(name, model, dut_handle)
        self.runtime_state = RuntimeState(model)
        self._predictor = RuntimePredictor(model, runtime_state=self.runtime_state, logger_name=f"ral.{name}")

    def disable_check(self, name_or_addr: Union[str, int], field_name: str = ""):
        self.runtime_state.disable_check(name_or_addr, field_name)

    def enable_check(self, name_or_addr: Union[str, int], field_name: str = ""):
        self.runtime_state.enable_check(name_or_addr, field_name)

    def set_predicted(self, name_or_addr: Union[str, int], value: int):
        reg = self.get_register(name_or_addr)
        for f in reg.fields:
            self.runtime_state.set_field_mirrored(reg.address, f.name, (value >> f.lsb) & f.mask)

    def set_field_predicted(self, reg_name: str, field_name: str, value: int):
        reg = self.get_register(reg_name)
        self.runtime_state.set_field_mirrored(reg.address, field_name, value)
