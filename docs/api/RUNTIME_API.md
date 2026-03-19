# Runtime API

This is the recommended API for new code.

## `RuntimeRAL`

Runtime-backed RAL that separates spec from runtime state.

### Example

```python
from cocotbext.ral import RuntimeRAL

ral = RuntimeRAL("demo", model)

await ral.write("CTRL", 1)
val = await ral.read("CTRL")
```

## `SafeRuntimeRAL`

Adds strict RMW protection.

### Example

```python
from cocotbext.ral import SafeRuntimeRAL

ral = SafeRuntimeRAL("demo", model)

# Raises if unsafe
await ral.write_field("CTRL", "enable", 1)
```

## `IntegratedRuntimeRAL`

Full-featured runtime RAL with backdoor support.

### Example

```python
from cocotbext.ral import IntegratedRuntimeRAL

ral = IntegratedRuntimeRAL("tile0", model)

print(ral.dump_runtime_state())
```

## `RuntimePredictor`

Prediction engine backed by runtime state.

### Example

```python
predictor = ral._predictor
predictor.predict_write(0x0, 1)
result = predictor.predict_read(0x0, 1)
```

## `RuntimeState`

Holds all mutable state.

### Example

```python
state = ral.runtime_state
print(state)
```
