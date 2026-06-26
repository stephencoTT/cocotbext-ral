"""One register spec reused across many tiles: address offset + backdoor.

Demonstrates two scaling features together:

  * ``address_offset`` -- one ``RegisterModel`` driven through several physical
    maps (one ``RuntimeRAL`` per tile, each at a different bus base), and
  * ``PrefixBackdoorResolver`` -- the same spec HDL paths resolved onto each
    tile's concrete hierarchy for backdoor access.

Runs standalone with a dict-backed fake master (no cocotb/simulator needed):

    python examples/backdoor_tiled.py
"""

import asyncio

from cocotbext.ral import RegisterModel, Register, RegisterField, SwAccess, RuntimeRAL
from cocotbext.ral.backdoor import PrefixBackdoorResolver


class FakeApbMaster:
    def __init__(self):
        self.mem = {}

    async def write(self, addr, value):
        self.mem[addr] = value

    async def read(self, addr):
        return self.mem.get(addr, 0).to_bytes(4, "little")


def build_tile_spec() -> RegisterModel:
    """One tile's register map (addresses are tile-relative)."""
    model = RegisterModel("tile")
    model.add_register(Register("CTRL", address=0x0, size_bits=32, fields=[
        RegisterField("enable", lsb=0, msb=0, reset_value=0, sw_access=SwAccess.RW,
                      hdl_path="ctrl_reg.enable"),
        RegisterField("mode", lsb=1, msb=2, reset_value=0, sw_access=SwAccess.RW,
                      enum={"IDLE": 0, "RUN": 1, "HALT": 2}, hdl_path="ctrl_reg.mode"),
    ]), hierarchical_name="tile.CTRL")
    return model


async def main():
    spec = build_tile_spec()

    # A 2x2 grid of tiles, each at a 0x1000 stride and a distinct HDL prefix.
    rals = {}
    for x in range(2):
        for y in range(2):
            base = (x * 2 + y) * 0x1000
            ral = RuntimeRAL(
                f"tile_{x}_{y}",
                spec,                                   # same spec, shared
                address_offset=base,                    # distinct physical map
                backdoor_resolver=PrefixBackdoorResolver(f"dut.gen_x[{x}].gen_y[{y}].tile"),
            )
            ral.attach_master(FakeApbMaster(), protocol="apb")
            rals[(x, y)] = ral

    # Program each tile's mode via its symbolic enum name; independent state.
    await rals[(0, 0)].write_field("tile.CTRL", "mode", "RUN")
    await rals[(1, 1)].write_field("tile.CTRL", "mode", "HALT")

    mode_field = spec.get_register("tile.CTRL").get_field("mode")
    for (x, y), ral in rals.items():
        mode_name = mode_field.enum_name(ral.mirror_field("tile.CTRL", "mode"))
        bd = ral.resolve_field_backdoor_path("tile.CTRL", "mode")
        print(f"tile_{x}_{y}: mode={mode_name!s:5}  backdoor={bd}")


if __name__ == "__main__":
    asyncio.run(main())
