"""Search and bulk-access APIs over a replicated (DMA0..DMA7) register map.

Runs standalone -- no cocotb simulator needed. A tiny dict-backed fake
master stands in for a real cocotbext VIP master so the bulk transaction
APIs can be demonstrated end-to-end:

    python examples/search_and_bulk.py
"""

import asyncio

from cocotbext.ral import (
    RegisterModel, Register, RegisterField, SwAccess, RuntimeRAL,
)


# --------------------------------------------------------------------------
# A small dict-backed "bus master" with the same write()/read() shape the
# RAL expects from an APB master. Real code attaches a cocotbext master.
# --------------------------------------------------------------------------
class FakeApbMaster:
    def __init__(self):
        self.mem = {}

    async def write(self, addr, value):
        self.mem[addr] = value

    async def read(self, addr):
        return self.mem.get(addr, 0).to_bytes(4, "little")


def build_model() -> RegisterModel:
    """Eight DMA engines, each with CTRL / STATUS / ADDR at a 0x100 stride."""
    model = RegisterModel("chip")
    for i in range(8):
        base = 0x1000 + i * 0x100
        model.add_register(Register("CTRL", address=base + 0x0, fields=[
            RegisterField("enable", lsb=0, msb=0, reset_value=0, sw_access=SwAccess.RW),
            RegisterField("burst",  lsb=1, msb=3, reset_value=0, sw_access=SwAccess.RW),
        ]), hierarchical_name=f"chip.DMA{i}.CTRL")
        model.add_register(Register("STATUS", address=base + 0x4, fields=[
            RegisterField("busy", lsb=0, msb=0, reset_value=0, sw_access=SwAccess.RO),
            RegisterField("err",  lsb=1, msb=1, reset_value=0, sw_access=SwAccess.W1C),
        ]), hierarchical_name=f"chip.DMA{i}.STATUS")
        model.add_register(Register("ADDR", address=base + 0x8, fields=[
            RegisterField("ptr", lsb=0, msb=31, reset_value=0, sw_access=SwAccess.RW),
        ]), hierarchical_name=f"chip.DMA{i}.ADDR")
    return model


def search_demo(model: RegisterModel) -> None:
    """Model-level search -- pure query, no bus / cocotb needed."""
    ctrls = model.find_registers(name="chip.DMA*.CTRL")
    print(f"find_registers('chip.DMA*.CTRL') -> {len(ctrls)} registers")

    dma3 = model.find_registers(hierarchy_prefix="chip.DMA3")
    print(f"find_registers(hierarchy_prefix='chip.DMA3') -> "
          f"{[r.hierarchical_name for r in dma3]}")

    w1c = model.find_fields(access=SwAccess.W1C)
    print(f"find_fields(access=W1C) -> {len(w1c)} (register, field) pairs")

    by_engine = model.group_by(lambda r: r.hierarchical_name.split(".")[1])
    print(f"group_by(engine) -> {len(by_engine)} groups, "
          f"DMA0 has {len(by_engine['DMA0'])} registers")


async def bulk_demo(model: RegisterModel) -> None:
    """RAL-level bulk access -- drives transactions through the master."""
    ral = RuntimeRAL("chip", model)
    ral.attach_master(FakeApbMaster(), protocol="apb")

    # Same field value across every DMA CTRL that has 'enable'.
    touched = await ral.write_field_pattern("chip.DMA*.CTRL", "enable", 1)
    print(f"\nwrite_field_pattern(enable=1) -> wrote {len(touched)} registers")

    # Heterogeneous bulk write, address-sorted by default.
    await ral.write_many({
        "chip.DMA0.ADDR": 0x1000,
        "chip.DMA1.ADDR": 0x2000,
        "chip.DMA2.ADDR": 0x3000,
    })
    print("write_many(3 ADDR regs) -> done")

    # Read every DMA status back in one call.
    status = await ral.read_pattern("chip.DMA*.STATUS")
    print(f"read_pattern('chip.DMA*.STATUS') -> {len(status)} reads, "
          f"e.g. chip.DMA0.STATUS = 0x{status['chip.DMA0.STATUS']:x}")

    # Mirror reflects the bulk writes (no bus traffic for this query).
    print(f"mirror chip.DMA0.CTRL.enable = "
          f"{ral.mirror_field('chip.DMA0.CTRL', 'enable')}")


def main() -> None:
    model = build_model()
    print(f"Built model with {model.register_count} registers\n")
    search_demo(model)
    asyncio.run(bulk_demo(model))


if __name__ == "__main__":
    main()
