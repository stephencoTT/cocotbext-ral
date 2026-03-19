"""Minimal AXI-Lite cocotb demo using cocotbext-ral.

This example is intentionally lightweight and is meant to show how the RAL is
wired into a cocotb test, not to provide a complete standalone DUT.
"""

import cocotb
from cocotbext.axi import AxiLiteBus, AxiLiteMaster
from cocotbext.ral import RAL
from cocotbext.ral.adapters import load_json


@cocotb.test()
async def test_axil_register_access(dut):
    model = load_json("registers.json")

    ral = RAL("demo", model, dut_handle=dut)
    master = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axil"), dut.clk, dut.rst)
    ral.attach_master(master, protocol="axil")

    await ral.write("CTRL", 0x1)
    ctrl = await ral.read("CTRL")

    await ral.write_field("CTRL", "enable", 1)
    enable = await ral.read_field("CTRL", "enable")

    cocotb.log.info(f"CTRL=0x{ctrl:x} enable={enable}")
    ral.raise_on_errors()
