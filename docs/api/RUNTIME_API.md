# Runtime API

## IntegratedRuntimeRAL

The recommended entry point. Combines runtime state, RMW safety, backdoor resolution, and transaction logging.

```python
from cocotbext.ral import IntegratedRuntimeRAL
from cocotbext.ral.adapters import load_json
from cocotbext.ral.backdoor import PrefixBackdoorResolver

model = load_json("registers.json")

ral = IntegratedRuntimeRAL(
    name="tile_3_4",
    model=model,
    dut_handle=dut,                                          # optional, for backdoor
    backdoor_resolver=PrefixBackdoorResolver("dut.tile_3_4"), # optional
    txn_log="register_txns.log",                              # optional
)
ral.attach_master(master, protocol="axi", interface="dut.axi_master")
```

### Front-door access

```python
# Write by address or name
await ral.write(0x100, 0xDEADBEEF)
await ral.write("block.CTRL", 0x01)

# Read with automatic prediction checking
val = await ral.read(0x100)
val = await ral.read("CTRL")

# Field-level access (RMW with safety check)
await ral.write_field("CTRL", "enable", 1)
en = await ral.read_field("CTRL", "enable")
```

### Mirror update modes

The RAL keeps a mirror (aka "predicted value") of every field. Three APIs
mutate the mirror, differing in whether they drive the bus and whether they
respect access-policy semantics.

| API | Bus traffic? | Mirror update style | When to use |
|---|---|---|---|
| `await ral.write(reg, data)` | **Yes** — drives the bus | Applies access policy (W1C clears, WO stores, RO no-op) | Normal SW write from this RAL. |
| `ral.notify_external_write(addr, data)` | No | Applies access policy | Another agent (firmware, a second master) did a SW-style write; keep the mirror honest. |
| `ral.set_predicted(reg, value)` / `set_field_predicted(reg, field, v)` | No | **Raw overwrite** — ignores policy | Hardware drove a change (e.g. `hwset` / `hwclr`) and you want the mirror to reflect reality. |

"Predicted" and "mirror" refer to the same internal shadow — they're used
interchangeably in logs and method names.

Concrete differences for a W1C field whose mirror currently reads `0x0`:

- `set_predicted(STAT, 0x01)` → mirror becomes `0x01` (bit forced set).
- `notify_external_write(STAT, 0x01)` → mirror stays `0x00` (W1C policy: writing 1 clears, so 0→0).
- `await ral.write(STAT, 0x01)` → same as above *and* the bus transaction is driven.

```python
# Set predicted value manually
ral.set_predicted("CTRL", 0x42)
ral.set_field_predicted("CTRL", "enable", 1)

# Disable/enable checking
ral.disable_check("CTRL")              # all fields
ral.disable_check("CTRL", "status")    # single field
ral.enable_check("CTRL")

# Notify about external writes (firmware, other masters)
ral.notify_external_write(0x100, 0xAB)

# Reset model to defaults
ral.reset()
```

### Search and bulk access

Searching the register model and driving bulk transactions is built into
the RAL so test code doesn't have to hand-roll loops over instance-indexed
hierarchies (e.g. `DMA0..DMA7`).

**Model-level search (pure query, no cocotb needed):**

```python
# All DMA CTRL registers across every instance.
ctrls = model.find_registers(name="chip.DMA*.CTRL")

# Regex form for more complex matches.
stats = model.find_registers(regex=r"DMA[0-3]\.STATUS")

# All registers containing at least one W1C field.
w1c_regs = model.find_registers(access=SwAccess.W1C)

# Narrow the search to a subtree.
dma3 = model.find_registers(hierarchy_prefix="chip.DMA3")

# Compose any of the above with an arbitrary predicate.
wide = model.find_registers(predicate=lambda r: r.size_bytes == 8)

# (register, field) pairs — useful for "walk every RO field".
ro = model.find_fields(access=SwAccess.RO)
# Combine filters: every W1C status bit across the DMAs.
dma_w1c = model.find_fields(
    reg_name="chip.DMA*.STATUS",
    access=SwAccess.W1C,
)

# Group registers by instance (e.g. DMA0 -> [CTRL, STATUS, ADDR]).
by_engine = model.group_by(lambda r: r.hierarchical_name.split(".")[1])
```

**RAL-level bulk access (drives transactions):**

```python
# Same value to every matched register.
await ral.write_pattern("chip.DMA*.CTRL", 0x1)

# Same field value across every register that has that field.
await ral.write_field_pattern("chip.DMA*.CTRL", "enable", 1)

# Readback every DMA status in one call.
status = await ral.read_pattern("chip.DMA*.STATUS")
# {"chip.DMA0.STATUS": 0x2, "chip.DMA1.STATUS": 0x0, ...}

# Heterogeneous bulk write. Address-sorted by default.
await ral.write_many({
    "chip.DMA0.ADDR": 0x1000,
    "chip.DMA1.ADDR": 0x2000,
    "chip.DMA2.ADDR": 0x3000,
})

# Collect errors instead of raising on first failure.
results = await ral.write_many(values, best_effort=True)
failed = {k: e for k, e in results.items() if e is not None}
```

**Semantics reference:**

| API | Returns | If no match |
|---|---|---|
| `model.find_registers(...)` | `List[Register]` sorted by address | `[]` |
| `model.find_fields(...)` | `List[(Register, RegisterField)]` sorted by `(addr, lsb)` | `[]` |
| `model.group_by(key)` | `Dict[Any, List[Register]]` (groups sorted by address) | `{}` |
| `await ral.write_pattern(pat, val)` | `List[str]` matched names | raises `KeyError` |
| `await ral.write_field_pattern(pat, field, val)` | `List[str]` names that *contain* the field | raises `KeyError` |
| `await ral.read_pattern(pat)` | `Dict[str, int]` in address order | raises `KeyError` |
| `await ral.write_many(values, sort=True, best_effort=False)` | `Dict[key, Optional[Exception]]` | fail-fast raises; `best_effort=True` captures and continues |

`name=` args are **fnmatch globs** (`*`, `?`, `[...]`) unless you pass
`regex=` instead. The two are mutually exclusive.

### Backdoor access

```python
# Resolve HDL paths
path = ral.resolve_register_backdoor_path("CTRL")
path = ral.resolve_field_backdoor_path("CTRL", "enable")

# Direct HDL read/write (requires dut_handle)
val = await ral.backdoor_read("CTRL")
await ral.backdoor_write("CTRL", 0x42)

# Set HDL paths at runtime
ral.set_hdl_path("CTRL", "ctrl_reg")
ral.set_field_hdl_path("CTRL", "enable", "ctrl_reg.enable")
```

### Transaction logging

```python
# Phase annotations appear in the log
ral.set_txn_phase("Phase 1: Reset value check")

# Write summary and close
ral.write_txn_summary()
ral.close_txn_log()
```

**RMW entries are grouped.** A single `write_field(reg, field, value)` call
performs a read-modify-write but produces **one** `WRITE_FIELD` log entry.
The internal bus read and write-back are rendered as nested child lines
under a `Bus traffic:` section, so each field write is one numbered
transaction rather than three:

```
--- TXN #079 @ 1.90us -----------------------------------------------
  Operation  : WRITE_FIELD (RMW)
  Model Path : edc_biu_top.edc_biu.CTRL
  Field      : RSVD
  Field Value: 0x1
  Full Write : 0x00000001  (read 0x00000000, mask 0x00000001)
  RMW Safety : SAFE (all neighbors are RW)
  Mirror     : 0x00000000 -> 0x00000001
  Bus traffic:
    READ   @ 1.88us     0x00000008 -> 0x00000000  (PASS)
    WRITE  @ 1.90us     0x00000008 <- 0x00000001
```

Advanced: the `TransactionLogger.begin_rmw()` / `end_rmw()` hooks expose
the buffering mechanism for custom wrappers. Typical test code never calls
these directly — `IntegratedRuntimeRAL.write_field()` uses them internally.

### Debug

```python
# Dump all runtime state
print(ral.dump_runtime_state())

# Compare expected vs actual for a register
print(ral.diff_runtime_state(actual_value, address))

# Reporting
print(ral.report())
assert not ral.has_errors()
ral.raise_on_errors()
```

## SafeRuntimeRAL

Extends RuntimeRAL with RMW safety checking. `write_field()` raises `RuntimeError` if the read-modify-write would be unsafe (non-RW neighbor fields).

```python
from cocotbext.ral import SafeRuntimeRAL

ral = SafeRuntimeRAL("ip", model, dut_handle=dut)
ral.attach_master(master, protocol="axil")

# Safe: all-RW register
await ral.write_field("SCRATCH", "data", 0x42)

# Raises RuntimeError: RO neighbor "status" makes RMW unsafe
await ral.write_field("MIXED_REG", "ctrl", 0x01)
```

## RuntimeRAL

Base runtime-backed RAL without RMW safety or backdoor. Use this when you don't need safety checks and want a lighter class.

```python
from cocotbext.ral import RuntimeRAL

ral = RuntimeRAL("ip", model)
ral.attach_master(master, protocol="apb")

# State management via runtime_state
ral.runtime_state.disable_check(0x100, "status")
ral.runtime_state.set_field_mirrored(0x100, "ctrl", 0x42)
```

## RuntimePredictor

Standalone prediction engine. Works without cocotb.

```python
from cocotbext.ral.runtime_predictor import RuntimePredictor

pred = RuntimePredictor(model)

# Predict write
pred.predict_write(0x100, 0xDEADBEEF)

# Predict read and check
result = pred.predict_read(0x100, 0xDEADBEEF)
assert result.passed
assert len(result.error_messages) == 0

# Access runtime state
state = pred.runtime_state.get_register_state(0x100)
print(f"Mirrored: 0x{state.predicted_value:x}")
```

## RuntimeState

Per-instance mutable state. Created automatically by RuntimeRAL, or manually.

```python
from cocotbext.ral.state import RuntimeState

state = RuntimeState(model)

# Query state
reg_state = state.get_register_state(0x100)  # by address
reg_state = state.get_register_state("CTRL")  # by name
print(reg_state.fields["enable"].mirrored)

# Modify state
state.set_field_mirrored(0x100, "enable", 1)
state.disable_check(0x100, "status")
state.enable_check(0x100)

# Reset all state
state.reset()

# Sync with legacy RegisterField objects
state.sync_from_legacy_model()
state.sync_to_legacy_model()
```

## AccessPolicy

Per-field behavioral policy. Created via PolicyRegistry.

```python
from cocotbext.ral.access_policy import AccessPolicy, PolicyRegistry

registry = PolicyRegistry()
policy = registry.policy_for(field)

# Write behavior
policy.apply_write(field, field_state, write_value)

# Read side effects (RCLR clears, RSET sets all bits)
policy.apply_read_side_effect(field, field_state)

# Check behavior
should_check = policy.check_on_read(field, field_state)
```

## RMW Safety Assessment

```python
from cocotbext.ral.rmw_policy import assess_field_rmw

assessment = assess_field_rmw(register, "target_field_name")
print(assessment.safe)      # True or False
print(assessment.reasons)   # list of reason strings
```
