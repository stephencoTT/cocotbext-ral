# Integration and Loaders

## JSON Loader

```python
from cocotbext.ral.adapters import load_json

model = load_json("registers.json")
```

## RDL Loader

```python
from cocotbext.ral.adapters import load_rdl

model = load_rdl("regs.rdl")
```

## Backdoor Resolver

```python
resolver = PrefixBackdoorResolver("dut.tile0")
ral = IntegratedRuntimeRAL("tile0", model, backdoor_resolver=resolver)
```

## Debug Helpers

```python
print(ral.dump_runtime_state())
print(ral.diff_runtime_state(actual, addr))
```
