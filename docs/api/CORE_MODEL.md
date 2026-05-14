# Core Model API

## SwAccess

Software access types for register fields.

```python
from cocotbext.ral import SwAccess

SwAccess.RW      # Read-write
SwAccess.RO      # Read-only (volatile by default)
SwAccess.WO      # Write-only
SwAccess.W1C     # Write-1-to-clear (alias: WOCLR)
SwAccess.W1S     # Write-1-to-set (alias: WOSET)
SwAccess.RCLR    # Read-clear (volatile by default, alias: RC)
SwAccess.RSET    # Read-set (volatile by default, alias: RS)
```

## RegisterField

A single bit-field within a register.

```python
from cocotbext.ral import RegisterField, SwAccess

field = RegisterField(
    name="irq_status",
    lsb=0,
    msb=7,
    reset_value=0xFF,
    sw_access=SwAccess.W1C,
    hdl_path="ctrl_reg.irq_status",  # optional, for backdoor access
    volatile=None,                    # None = auto-infer from access type
)

field.width          # 8
field.mask            # 0xFF
field.is_writable     # True (W1C is writable)
field.is_volatile     # False (W1C is not volatile by default)
field.is_checkable_on_read  # True
```

Volatile inference: if `volatile` is `None` (default), RO/RCLR/RSET fields are volatile. Explicit `volatile=True/False` overrides this.

## Register

A register containing one or more fields.

```python
from cocotbext.ral import Register, RegisterField, SwAccess

reg = Register(
    name="CTRL",
    address=0x100,
    size_bits=32,
    fields=[
        RegisterField("enable", lsb=0, msb=0, sw_access=SwAccess.RW),
        RegisterField("status", lsb=8, msb=15, reset_value=0xAA, sw_access=SwAccess.RO),
        RegisterField("irq", lsb=16, msb=23, reset_value=0xFF, sw_access=SwAccess.W1C),
    ],
    hdl_path="",        # optional register-level backdoor path
    description="",
)

reg.predicted_value      # composite of all field predicted values
reg.reset_value          # composite of all field reset values
reg.has_backdoor         # True if any field or register has hdl_path
reg.get_field("enable")  # returns RegisterField or None
reg.get_writable_mask()  # 0x00FF0001 (RW + W1C bits)
reg.get_checkable_mask() # 0x00FF0001 (RW + W1C; RO is volatile, not checked)
reg.reset()              # restore all fields to reset values
```

## RegisterModel

Top-level container with address and name indexing.

```python
from cocotbext.ral import RegisterModel

model = RegisterModel("my_ip")
model.add_register(reg, hierarchical_name="block.subsystem.CTRL")

# Lookup by address
ctrl = model.get_register(0x100)

# Lookup by full hierarchical name
ctrl = model.get_register("block.subsystem.CTRL")

# Lookup by leaf name (if unambiguous)
ctrl = model.get_register("CTRL")

# Lookup by suffix
ctrl = model.get_register("subsystem.CTRL")

# Iterate
for reg in model.all_registers():
    print(f"0x{reg.address:08x}: {reg.hierarchical_name}")

model.register_count  # number of registers
model.reset()         # reset all registers to defaults
model.summary()       # formatted summary string
```

### Force-check RO fields

RO fields are volatile by default, so the predictor skips them on read.
For static RO fields (IDs, versions, capability bits) the verification
side can opt them into checking without modifying the RDL/JSON source:

```python
# Per-register: flip every RO field in this register to non-volatile
model.force_check_ro("ip.ID")

# Per-field: only flip one specific field
model.force_check_ro("ip.STATUS", field_name="version_major")

# Sledgehammer: flip every RO field in the entire model
model.force_check_all_ro()
```

Each call returns the number of fields actually flipped. Use sparingly —
only safe when the targeted RO fields are not hardware-driven, otherwise
you'll get false read mismatches.
