# Quick Start Guide

This guide shows how to use cocotbext-ral with different access policies.

## Basic Usage

```python
from cocotbext.ral import RegisterModel, Register, RegisterField, SwAccess

model = RegisterModel("demo")
model.add_register(Register("CTRL", 0x0, fields=[
    RegisterField("enable", 0, 0, sw_access=SwAccess.RW),
    RegisterField("status", 1, 1, sw_access=SwAccess.RO),
]))
```

## Access Policy Examples

### RW (read/write)
```python
field = RegisterField("f", 0, 7, sw_access=SwAccess.RW)
```

### W1C (write-1-to-clear)
```python
field = RegisterField("irq", 0, 7, sw_access=SwAccess.W1C)
```

### W1S (write-1-to-set)
```python
field = RegisterField("flag", 0, 7, sw_access=SwAccess.W1S)
```

### RCLR (read-clear)
```python
field = RegisterField("event", 0, 7, sw_access=SwAccess.RCLR)
```

### RSET (read-set)
```python
field = RegisterField("sticky", 0, 7, sw_access=SwAccess.RSET)
```

## Runtime Usage

```python
from cocotbext.ral import IntegratedRuntimeRAL

ral = IntegratedRuntimeRAL("demo", model)
await ral.write("CTRL", 1)
val = await ral.read("CTRL")
```
