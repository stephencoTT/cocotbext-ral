# Legacy API

This section documents the legacy API. It remains supported but is no longer the recommended path.

## `RAL`

Main cocotb-facing interface.

### Example

```python
ral = RAL("demo", model, dut_handle=dut)
await ral.write("CTRL", 1)
val = await ral.read("CTRL")
```

## `Predictor`

Legacy prediction engine.

### Example

```python
predictor = Predictor(model)
predictor.predict_write(0x0, 1)
```

## Migration

| Legacy | New |
|--------|-----|
| `RAL` | `IntegratedRuntimeRAL` |
| `Predictor` | `RuntimePredictor` |
