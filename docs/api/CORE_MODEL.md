# Core Model API

This section covers the structural register model used by both the legacy and runtime-backed paths.

## `RegisterModel`

Top-level container for registers.

Common methods:
- `add_register(reg, hierarchical_name="")`
- `get_register(name_or_addr)`
- `get_register_by_address(address)`
- `all_registers()`
- `reset()`
- `summary()`

### Example

```python
from cocotbext.ral import RegisterModel, Register, RegisterField, SwAccess

model = RegisterModel("demo")
model.add_register(
    Register(
        "CTRL",
        address=0x0,
        fields=[
            RegisterField("enable", lsb=0, msb=0, reset_value=0, sw_access=SwAccess.RW),
            RegisterField("mode", lsb=1, msb=2, reset_value=0, sw_access=SwAccess.RW),
        ],
    ),
    hierarchical_name="CTRL",
)

ctrl = model.get_register("CTRL")
print(ctrl.address)
print(model.summary())
```

## `Register`

Represents a single register.

Common properties:
- `name`
- `address`
- `size_bits`
- `size_bytes`
- `fields`
- `hierarchical_name`
- `reset_value`
- `predicted_value`
- `has_backdoor`

Common methods:
- `get_field(name)`
- `get_writable_mask()`
- `get_checkable_mask()`
- `reset()`

### Example

```python
reg = model.get_register("CTRL")
field = reg.get_field("enable")
print(reg.reset_value)
print(field.mask)
```

## `RegisterField`

Represents a single field within a register.

Common properties:
- `name`
- `lsb`
- `msb`
- `width`
- `mask`
- `reset_value`
- `sw_access`
- `hdl_path`

Legacy mutable properties:
- `predicted_value`
- `check_enabled`

## `SwAccess`

Supported built-in software access types:
- `RW`
- `RO`
- `WO`
- `WOCLR`
