# cocotbext-ral

A Python-native Register Abstraction Layer (RAL) for [cocotb](https://www.cocotb.org/).

`cocotbext-ral` brings a UVM-like register model experience into cocotb -- without the rigidity of SystemVerilog or the overhead of traditional UVM RAL.

It is designed to be:
- **data-driven** -- clean separation of register spec vs runtime state
- **Pythonic** -- simple, inspectable, extensible
- **practical** -- works today with cocotbext AXI/APB
- **extensible** -- supports custom access semantics, backdoor mapping, and advanced DV flows

## Highlights

- **Runtime-backed architecture** with clear spec/state separation
- **Full access-type coverage**: RW, RO, WO, W1C, W1S, RCLR, RSET
- **Smart volatile inference**: RO, RCLR, RSET fields are volatile by default (overridable)
- **Safe field writes** that reject unsafe read-modify-write sequences
- **Backdoor resolution** that scales to replicated blocks and chiplets
- **Legacy compatibility** for teams migrating from a traditional UVM-style API
- **Pure-Python introspection** for debug, tooling, and AI-assisted flows

## Architecture

```text
RegisterModel (spec, immutable-ish)
        |
    RuntimeState (mutable per-instance state)
        |
RuntimePredictor + AccessPolicy
        |
   RuntimeRAL --> SafeRuntimeRAL --> IntegratedRuntimeRAL
```

For a deeper explanation, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/API.md](docs/API.md), and [DESIGN.md](DESIGN.md).

## Installation

```bash
pip install cocotbext-ral
```

Optional extras:

```bash
pip install cocotbext-ral[cocotb]   # cocotb + cocotbext-axi
pip install cocotbext-ral[rdl]      # SystemRDL compiler
pip install cocotbext-ral[all]      # Everything
```

## Quick start (recommended path)

```python
import cocotb
from cocotbext.axi import AxiLiteMaster, AxiLiteBus
from cocotbext.ral import IntegratedRuntimeRAL
from cocotbext.ral.adapters import load_json

@cocotb.test()
async def test_registers(dut):
    model = load_json("registers.json")
    ral = IntegratedRuntimeRAL("my_ip", model, dut_handle=dut)
    master = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axil"), dut.clk, dut.rst)
    ral.attach_master(master, protocol="axil")

    await ral.write("CTRL", 1)
    val = await ral.read("CTRL")
    await ral.write_field("CTRL", "enable", 1)
    en = await ral.read_field("CTRL", "enable")
    ral.raise_on_errors()
```

## Choosing an API

| Class | Use case |
|---|---|
| `IntegratedRuntimeRAL` | **Recommended.** Runtime state + RMW safety + backdoor + debug |
| `SafeRuntimeRAL` | Runtime state + RMW safety checks |
| `RuntimeRAL` | Runtime state, no RMW checks |
| `RAL` | Legacy path (still supported, emits deprecation warning) |

## Standalone usage (no cocotb required)

The core model, predictor, and policy layers have zero dependencies:

```python
from cocotbext.ral import RegisterModel, Register, RegisterField, SwAccess
from cocotbext.ral.runtime_predictor import RuntimePredictor

model = RegisterModel("my_ip")
reg = Register("CTRL", address=0x0, size_bits=32, fields=[
    RegisterField("enable", lsb=0, msb=0, reset_value=0, sw_access=SwAccess.RW),
    RegisterField("irq", lsb=8, msb=15, reset_value=0xFF, sw_access=SwAccess.W1C),
])
model.add_register(reg, hierarchical_name="block.CTRL")

pred = RuntimePredictor(model)
pred.predict_write(0x0, 0x01)
result = pred.predict_read(0x0, 0x01)
assert result.passed
```

## Register loading

```python
from cocotbext.ral.adapters import load_json, load_rdl

model = load_json("registers.json")      # RDL-generated JSON
model = load_rdl("registers.rdl")        # SystemRDL source (requires systemrdl-compiler)
```

## Access types

| SwAccess | Write behavior | Read behavior | Volatile by default |
|---|---|---|---|
| `RW` | Update value | Check prediction | No |
| `RO` | Ignored | Not checked | Yes |
| `WO` | Update value | Not checked | No |
| `W1C` | Clear written-1 bits | Check prediction | No |
| `W1S` | Set written-1 bits | Check prediction | No |
| `RCLR` | Ignored | Clears to 0 after read | Yes |
| `RSET` | Ignored | Sets to all-1s after read | Yes |

Aliases: `WOCLR`=`W1C`, `WOSET`=`W1S`, `RC`=`RCLR`, `RS`=`RSET`

## API documentation

See [docs/API.md](docs/API.md) for a practical API reference covering:
- Core model classes
- Runtime-backed APIs
- Backdoor helpers
- Debug helpers
- Loaders and common imports

## Testing

```bash
pip install -e .[dev]
pytest
```

136 tests covering: register model, legacy predictor, runtime predictor (all access types), access policies, RMW safety, backdoor resolvers, runtime state, volatile policy, debug helpers, checker, and JSON loader.

## Status

The runtime-backed classes (`IntegratedRuntimeRAL`, `SafeRuntimeRAL`, `RuntimeRAL`) are the recommended path. The legacy `RAL` and `Predictor` classes remain supported but emit deprecation warnings on instantiation.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
