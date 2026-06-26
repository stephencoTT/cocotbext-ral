# Quick Start Guide

## 1. Define a register model

```python
from cocotbext.ral import RegisterModel, Register, RegisterField, SwAccess

model = RegisterModel("my_ip")
model.add_register(Register("CTRL", address=0x0, fields=[
    RegisterField("enable", 0, 0, reset_value=0, sw_access=SwAccess.RW),
    RegisterField("mode", 1, 2, reset_value=0, sw_access=SwAccess.RW),
    RegisterField("status", 8, 15, reset_value=0xAA, sw_access=SwAccess.RO),
    RegisterField("irq", 16, 23, reset_value=0xFF, sw_access=SwAccess.W1C),
]), hierarchical_name="block.CTRL")

model.add_register(Register("SCRATCH", address=0x4, fields=[
    RegisterField("data", 0, 31, reset_value=0, sw_access=SwAccess.RW),
]), hierarchical_name="block.SCRATCH")
```

## 2. Or load from JSON / RDL

```python
from cocotbext.ral.adapters import load_json, load_rdl

model = load_json("registers.json")
model = load_rdl("regs.rdl", top_name="my_ip", incdir=["rdl_includes/"])
```

## 3. Create a RAL instance

```python
from cocotbext.ral import RuntimeRAL

ral = RuntimeRAL(
    name="my_ip",
    model=model,
    dut_handle=dut,          # optional: enables backdoor access
    txn_log=True,            # optional: writes register_txns.log
)
ral.attach_master(master, protocol="axi", interface="dut.axi_master")
```

## 4. Write and read registers

```python
# By address
await ral.write(0x4, 0xDEADBEEF)
val = await ral.read(0x4)

# By name
await ral.write("SCRATCH", 0xCAFEBABE)
val = await ral.read("block.SCRATCH")
```

The predictor automatically checks reads against the expected mirror value.

## 5. Field-level access

```python
# Read a single field
en = await ral.read_field("CTRL", "enable")

# Write a single field (read-modify-write with safety check)
await ral.write_field("SCRATCH", "data", 0x42)
```

`write_field` raises `RuntimeError` if the RMW is unsafe (non-RW neighbor fields).

## 6. Access type examples

### W1C (write-1-to-clear)

```python
field = RegisterField("irq", 0, 7, reset_value=0xFF, sw_access=SwAccess.W1C)
# Writing 0x0F clears bits 0-3: predicted value becomes 0xF0
```

### W1S (write-1-to-set)

```python
field = RegisterField("flags", 0, 7, reset_value=0, sw_access=SwAccess.W1S)
# Writing 0x03 sets bits 0-1: predicted value becomes 0x03
# Writing 0x0C adds bits 2-3: predicted value becomes 0x0F
```

### RCLR (read-clear)

```python
field = RegisterField("counter", 0, 7, reset_value=0xAB, sw_access=SwAccess.RCLR)
# After read: value clears to 0 (read side effect)
# RCLR fields are volatile by default (not prediction-checked)
```

### RSET (read-set)

```python
field = RegisterField("sticky", 0, 7, reset_value=0, sw_access=SwAccess.RSET)
# After read: value sets to 0xFF (read side effect)
# RSET fields are volatile by default (not prediction-checked)
```

## 7. Prediction control

```python
# Manually set expected value
ral.set_predicted("CTRL", 0x42)
ral.set_field_predicted("CTRL", "enable", 1)

# Disable checking for volatile/unpredictable registers
ral.disable_check("CTRL", "status")

# Notify predictor about external accesses by another agent (no bus traffic)
ral.notify_external_write(0x0, 0xFF)   # applies write policy (W1C clears, etc.)
ral.notify_external_read(0x0)          # applies read side-effects (RCLR -> 0, RSET -> all-1s)

# Reset model to defaults
ral.reset()
```

## 8. Check results

```python
print(ral.report())
assert not ral.has_errors()
ral.raise_on_errors()
ral.close_txn_log()
```

## 9. Multi-instance usage

One model, multiple tile instances with independent state:

```python
model = load_json("tile_registers.json")

ral_tile_a = RuntimeRAL("tile_a", model, txn_log="tile_a.log")
ral_tile_b = RuntimeRAL("tile_b", model, txn_log="tile_b.log")

# Each has independent RuntimeState
await ral_tile_a.write(0x100, 0xAAAA)
await ral_tile_b.write(0x100, 0xBBBB)
# ral_tile_a mirror = 0xAAAA, ral_tile_b mirror = 0xBBBB
```

## 10. Backdoor resolution for tiled designs

```python
from cocotbext.ral.backdoor import PrefixBackdoorResolver

ral = RuntimeRAL(
    "tile_3_4", model,
    backdoor_resolver=PrefixBackdoorResolver("dut.gen_x[3].gen_y[4].tile"),
)
# hdl_path "ctrl_reg" resolves to "dut.gen_x[3].gen_y[4].tile.ctrl_reg"
```
