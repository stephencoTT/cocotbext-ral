# cocotbext-ral

[![test](https://github.com/stephencoTT/cocotbext-ral/actions/workflows/test.yml/badge.svg)](https://github.com/stephencoTT/cocotbext-ral/actions/workflows/test.yml)

A Python-native Register Abstraction Layer (RAL) for [cocotb](https://www.cocotb.org/).

`cocotbext-ral` provides UVM-like register modeling, access-type-aware prediction, and automated checking -- all in pure Python, designed for cocotb hardware verification.

## Features

- **Runtime-backed architecture** with clean separation of register spec vs mutable state
- **Full access-type coverage**: RW, RO, WO, W1C, W1S, RCLR, RSET
- **Smart volatile inference**: RO, RCLR, RSET fields default to volatile (overridable)
- **Safe field writes** that reject unsafe read-modify-write sequences, plus byte-strobe partial writes
- **Field enumerations & reset domains** -- symbolic field values and soft/secondary resets
- **Backdoor resolution** and **multiple address maps** that scale to replicated blocks and chiplets
- **Wide-register splitting**, **bus-response checking**, and **pre/post access callbacks**
- **Transaction logging** with detailed per-transaction file output
- **Pure-Python core** -- model, predictor, and policies work without cocotb
- **cocotb 1.x and 2.x** compatible

## Architecture

```
RegisterModel (spec)
        |
    RuntimeState (per-instance mutable state)
        |
RuntimePredictor + AccessPolicy
        |
     RuntimeRAL  -- front-door bus + prediction/checking, RMW safety,
        |          backdoor resolution, and transaction logging
   Backdoor / Transaction Log
```

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

### cocotb 1.x and 2.x

`cocotbext-ral` works on both cocotb 1.x and cocotb 2.x. Under **cocotb 2.x**
you need a `cocotbext-axi` build that is itself cocotb-2.x compatible; the
public PyPI release may lag, in which case install a patched/forked build:

```bash
pip install "cocotb>=2.0" cocotbext-axi
```

(The library itself ships type hints — `py.typed` — so editors and `mypy` see them.)

## Quick start

### With cocotb simulation

```python
import cocotb
from cocotbext.axi import AxiLiteMaster, AxiLiteBus
from cocotbext.ral import RuntimeRAL
from cocotbext.ral.adapters import load_json

@cocotb.test()
async def test_registers(dut):
    model = load_json("registers.json")

    ral = RuntimeRAL("my_ip", model, dut_handle=dut, txn_log=True)
    master = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axil"), dut.clk, dut.rst)
    ral.attach_master(master, protocol="axil", interface="dut.s_axil")

    # Write and read with automatic prediction checking
    await ral.write("CTRL", 0x01)
    val = await ral.read("CTRL")

    # Field-level access with RMW safety
    await ral.write_field("CTRL", "enable", 1)
    en = await ral.read_field("CTRL", "enable")

    # Check results
    ral.raise_on_errors()
    ral.close_txn_log()
```

### Standalone (no cocotb)

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

## API classes

| Class | Description |
|---|---|
| `RuntimeRAL` | The RAL: runtime-state-backed prediction + front-door bus, RMW safety, backdoor resolution, and transaction logging |
| `RuntimePredictor` | Standalone prediction engine (no cocotb needed) |
| `RuntimeState` | Per-instance mutable register state |
| `AccessPolicy` | Per-field read/write behavior |
| `TransactionLogger` | Detailed file-based transaction logging |
| `BackdoorResolver` | HDL path resolution (base, Prefix, Mapping variants) |
| `RegisterModel` | Structural register specification |

## Register loading

```python
from cocotbext.ral.adapters import load_json, load_rdl

model = load_json("registers.json")                        # RDL-generated JSON
model = load_rdl("regs.rdl", top_name="my_ip", incdir=[])  # SystemRDL source
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

## Transaction logging

Enable detailed per-transaction file output:

```python
# Default filename (register_txns.log)
ral = RuntimeRAL("ip", model, txn_log=True)

# Custom path
ral = RuntimeRAL("ip", model, txn_log="my_regs.log")

# Phase annotations
ral.set_txn_phase("Phase 1: Reset value check")
await ral.write(addr, value)

# Summary and close
ral.close_txn_log()
```

Each transaction entry includes: model path, address, data, protocol, interface HDL path, status (PASS/FAIL/SKIP), mirror state, per-field breakdown, and RMW safety assessment.

## Testing

```bash
pip install -e .[dev,rdl]
pytest                       # pure-Python unit tests
ruff check cocotbext/        # lint
mypy                         # type-check
```

196 pure-Python tests covering: register model (including search / group helpers, field enums, reset domains), runtime predictor (all access types, external-read side-effects), access policies, RMW safety, backdoor resolvers (including cocotb 1.x/2.x value resolution), runtime state, volatile policy, debug helpers, checker, JSON loader, RDL loader, transaction logger, RuntimeRAL construction / reset / check-toggle helpers, and the completeness features (wide-register splitting, bus-response checking, byte-strobe partial writes, callbacks, memory burst, address-offset maps). (RDL loader tests require the `rdl` extra; they skip otherwise.)

## Documentation

Read in this order:

1. [Quick Start](docs/START_GUIDE.md) -- 10-step walkthrough covering all access types and the common flows.
2. [Architecture](docs/ARCHITECTURE.md) -- layer-by-layer design and the rationale behind each decision.
3. API reference (pick what you need):
   - [Core Model](docs/api/CORE_MODEL.md) -- `RegisterModel`, `Register`, `RegisterField`, `SwAccess`.
   - [Runtime API](docs/api/RUNTIME_API.md) -- `RuntimeRAL`, mirror update modes, RMW logging, search / bulk APIs.
   - [Integration and Loaders](docs/api/INTEGRATION_AND_LOADERS.md) -- JSON/RDL loaders, backdoor resolvers, transaction logging.

## License

MIT
