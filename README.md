# cocotbext-ral

Register Abstraction Layer (RAL) for [cocotb](https://www.cocotb.org/) verification environments.

`cocotbext-ral` provides a hierarchical register model with access-type-aware prediction, automatic checking, passive bus monitoring, and front-door/backdoor access — all driven from standard JSON or SystemRDL register descriptions.

## Installation

```bash
# Core package (pure Python — no cocotb required)
pip install cocotbext-ral

# With cocotb simulation support
pip install cocotbext-ral[cocotb]

# With SystemRDL loading support
pip install cocotbext-ral[rdl]

# Everything
pip install cocotbext-ral[all]

# Development install (from source)
git clone https://github.com/<org>/cocotbext-ral.git
cd cocotbext-ral
pip install -e ".[dev]"
```

## Overview

The package is organized into three tiers:

```
Tier 0 — Pure Python, zero dependencies
├── RegisterModel, Register, RegisterField, RegisterBlock
└── SwAccess (RW, RO, WO, WOCLR)

Tier 1 — Pure Python, uses Tier 0
├── Predictor    — access-type-aware write prediction and read checking
├── Checker      — scoreboard accumulation and reporting
├── load_json    — load register model from JSON
└── load_rdl     — load register model from SystemRDL (optional dep)

Tier 2 — Requires cocotb + cocotbext-axi
├── RAL          — top-level class: model + front-door + backdoor + monitor
├── ApbRalMonitor
├── AxiLiteRalMonitor
└── AxiRalMonitor
```

Tier 0 and 1 classes can be used **without cocotb** for offline analysis, register model exploration, or unit testing. Tier 2 classes require a cocotb simulation environment.

## Quick Start — Active Mode (cocotb)

```python
import cocotb
from cocotbext.axi import AxiLiteMaster, AxiLiteBus
from cocotbext.ral import RAL, RegisterModel
from cocotbext.ral.adapters import load_json

@cocotb.test()
async def test_registers(dut):
    # Load register description
    model = load_json("registers.json")

    # Create RAL and attach AXI-Lite master
    ral = RAL("my_ip", model, dut_handle=dut)
    master = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axil"), dut.clk, dut.rst)
    ral.attach_master(master, protocol="axil")

    # Write and read with automatic prediction checking
    await ral.write("CTRL", 0x1)
    value = await ral.read("CTRL")  # checks against predicted value

    # Field-level access (read-modify-write)
    await ral.write_field("CTRL", "enable", 1)
    en = await ral.read_field("CTRL", "enable")

    # Report results
    ral.raise_on_errors()
```

## Quick Start — Passive Monitor Mode

```python
@cocotb.test()
async def test_monitor(dut):
    model = load_json("registers.json")
    ral = RAL("my_ip", model)

    # Attach passive monitor — observes bus without driving
    ral.attach_monitor(
        bus=AxiLiteBus.from_prefix(dut, "s_axil"),
        clock=dut.clk,
        reset=dut.rst,
        protocol="axil",
    )

    # Run stimulus from other sources...
    # Monitor automatically checks all observed transactions

    ral.raise_on_errors()
```

## Quick Start — Pure Python Model (no cocotb)

```python
from cocotbext.ral import RegisterModel, RegisterField, Register, SwAccess
from cocotbext.ral.adapters import load_json

# Load and explore a register model
model = load_json("registers.json")
print(model.summary())

# Look up registers by name or address
ctrl = model.get_register("CTRL")
print(f"CTRL @ 0x{ctrl.address:08x}, {len(ctrl.fields)} fields")

for field in ctrl.fields:
    print(f"  {field.name}: [{field.msb}:{field.lsb}] {field.sw_access.name} reset=0x{field.reset_value:x}")
```

## API Reference

### Register Model (Tier 0)

| Class | Description |
|-------|-------------|
| `RegisterModel` | Top-level container with address and name-based lookup |
| `Register` | A register with address, size, fields, and composite predicted/reset values |
| `RegisterField` | A bit-field with position, access type, and predicted value tracking |
| `RegisterBlock` | Named group of registers sharing a base address |
| `SwAccess` | Enum: `RW`, `RO`, `WO`, `WOCLR` |

### Prediction Engine (Tier 1)

| Class | Description |
|-------|-------------|
| `Predictor` | Maintains per-field predictions; `predict_write()` updates, `predict_read()` checks |
| `PredictionResult` | Result of a read check with per-field details |
| `FieldResult` | Per-field comparison: expected vs actual, matched flag |
| `Checker` | Scoreboard that accumulates results and provides `report()` / `raise_on_errors()` |

### RAL (Tier 2 — cocotb)

| Method | Description |
|--------|-------------|
| `RAL(name, model, dut_handle)` | Create RAL instance |
| `attach_master(master, protocol)` | Attach cocotbext VIP for active mode (`"apb"`, `"axil"`, `"axi"`) |
| `attach_monitor(bus, clock, reset, protocol)` | Start passive bus monitor |
| `write(name_or_addr, value)` | Front-door write with prediction update |
| `read(name_or_addr) -> int` | Front-door read with prediction check |
| `write_field(reg, field, value)` | Read-modify-write a single field |
| `read_field(reg, field) -> int` | Read and extract a single field |
| `backdoor_read(name_or_addr) -> int` | Read via HDL path |
| `backdoor_write(name_or_addr, value)` | Force via HDL path |
| `set_predicted(name_or_addr, value)` | Manually override predicted value |
| `set_field_predicted(reg, field, value)` | Override a single field prediction |
| `reset()` | Restore all predictions to reset values |
| `report() -> str` | Summary of all checks |
| `raise_on_errors()` | Assert no mismatches |

### Monitors

| Class | Protocol | Signals |
|-------|----------|---------|
| `ApbRalMonitor` | APB | psel, penable, pready, paddr, pwrite, pwdata, prdata |
| `AxiLiteRalMonitor` | AXI-Lite | AW+W channels (writes), AR+R channels (reads) |
| `AxiRalMonitor` | AXI | Full AXI with burst support |

### Loaders

| Function | Description |
|----------|-------------|
| `load_json(path, model_name="")` | Load from RDL-generated JSON |
| `load_rdl(path, top_name="", incdir=[], model_name="")` | Load from SystemRDL source (requires `systemrdl-compiler`) |

## Register Description Formats

### JSON Format

The JSON loader expects the hierarchical format produced by RDL-to-JSON tools:

```json
{
    "type": "addrmap",
    "inst_name": "my_ip",
    "addr_offset": 0,
    "children": [
        {
            "type": "reg",
            "inst_name": "CTRL",
            "addr_offset": 0,
            "regsize": 32,
            "desc": "Control register",
            "children": [
                {
                    "type": "field",
                    "inst_name": "enable",
                    "lsb": 0,
                    "msb": 0,
                    "reset": 0,
                    "sw_access": "rw",
                    "woclr": 0
                }
            ]
        }
    ]
}
```

Container types (`addrmap`, `regfile`) accumulate `addr_offset` values as the hierarchy is traversed.

### SystemRDL

```python
from cocotbext.ral.adapters import load_rdl

model = load_rdl("my_ip.rdl", top_name="my_ip", incdir=["rdl/include"])
```

Requires the `systemrdl-compiler` optional dependency: `pip install cocotbext-ral[rdl]`.

## Running Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

All tests are pure Python and run without cocotb.

## License

MIT
