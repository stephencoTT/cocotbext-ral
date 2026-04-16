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

### Prediction control

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
