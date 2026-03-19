from typing import Optional

from .backdoor import BackdoorResolver
from .debug import dump_state, diff_state
from .safe_runtime_ral import SafeRuntimeRAL


class IntegratedRuntimeRAL(SafeRuntimeRAL):
    """Runtime RAL with backdoor resolution and debug helpers.

    This class is intended as the forward-looking entry point for the new
    runtime-backed architecture. It layers three things together:
      * RuntimeState-backed prediction/checking
      * conservative RMW protection for field writes
      * pluggable backdoor path resolution
    """

    def __init__(self, name, model, dut_handle=None, backdoor_resolver: Optional[BackdoorResolver] = None):
        super().__init__(name, model, dut_handle)
        self.backdoor_resolver = backdoor_resolver or BackdoorResolver()

    def resolve_register_backdoor_path(self, name_or_addr):
        reg = self.get_register(name_or_addr)
        return self.backdoor_resolver.resolve_register_path(reg)

    def resolve_field_backdoor_path(self, reg_name, field_name):
        reg = self.get_register(reg_name)
        field = reg.get_field(field_name)
        if field is None:
            raise KeyError(f"Field {field_name!r} not found in {reg.name}")
        return self.backdoor_resolver.resolve_field_path(reg, field)

    def dump_runtime_state(self) -> str:
        return dump_state(self.runtime_state)

    def diff_runtime_state(self, actual: int, address: int) -> str:
        return diff_state(self.runtime_state, actual, address)
