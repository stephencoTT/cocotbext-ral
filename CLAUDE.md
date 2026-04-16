# CLAUDE.md

## What this project is

`cocotbext-ral` is a Python-native Register Abstraction Layer (RAL) for cocotb hardware verification. It provides register modeling, access-type-aware prediction, automated checking, and transaction logging.

## Project structure

```
cocotbext/ral/
  register_model.py         # SwAccess, RegisterField, Register, RegisterBlock, RegisterModel
  state.py                  # FieldState, RegisterState, RuntimeState
  access_policy.py          # AccessPolicy, PolicyRegistry
  runtime_predictor.py      # RuntimePredictor (recommended predictor)
  predictor.py              # Predictor (legacy, warns on instantiation)
  checker.py                # Checker scoreboard
  ral.py                    # RAL (legacy, requires cocotb, warns on direct instantiation)
  runtime_ral.py            # RuntimeRAL (requires cocotb)
  safe_runtime_ral.py       # SafeRuntimeRAL (requires cocotb)
  integrated_runtime_ral.py # IntegratedRuntimeRAL (requires cocotb)
  transaction_logger.py     # TransactionLogger (optional file output)
  backdoor.py               # BackdoorResolver, PrefixBackdoorResolver, MappingBackdoorResolver
  rmw_policy.py             # RMW safety assessment
  volatile_policy.py        # Volatile field helpers
  debug.py                  # dump_state(), diff_state()
  monitor.py                # ApbRalMonitor, AxiLiteRalMonitor, AxiRalMonitor (requires cocotb)
  version.py                # __version__ = "0.2.0"
  experimental.py           # Stable import point for runtime APIs
  adapters/
    json_loader.py           # load_json()
    rdl_loader.py            # load_rdl() (requires systemrdl-compiler)
tests/                       # 146 pytest unit tests
examples/                    # Usage examples
docs/                        # Architecture and API documentation
```

## Class hierarchy

```
IntegratedRuntimeRAL   (backdoor + txn log + debug)
  -> SafeRuntimeRAL    (RMW safety)
    -> RuntimeRAL      (RuntimeState-backed prediction)
      -> RAL           (legacy cocotb integration)
```

## Running tests

```bash
python -m pytest tests/ -v
```

All 146 tests pass. Tests are pure Python (no cocotb simulation needed).

## Key design decisions

- **Spec/state separation**: `RegisterModel` = structure, `RuntimeState` = mutable state. One model can back many instances.
- **Policy-based access**: `AccessPolicy` encapsulates write/read behavior per `SwAccess` type.
- **Volatile inference**: RO, RCLR, RSET default to `volatile=True`. Override with explicit `volatile=` parameter.
- **Deprecation on instantiation**: Legacy `Predictor` and `RAL` warn on construction, not import. `RAL` skips warning for subclasses.
- **Transaction logging**: Optional, zero-overhead when disabled. Enabled via `txn_log=` on `IntegratedRuntimeRAL`.

## Common development tasks

### Adding a new SwAccess type

1. Add to `SwAccess` enum in `register_model.py`
2. Add write behavior in `AccessPolicy.apply_write()`
3. Add read side-effect in `AccessPolicy.apply_read_side_effect()`
4. Update `check_on_read()` if checkable
5. Update `_VOLATILE_ACCESS_TYPES` if volatile
6. Add tests

### Adding a new backdoor resolver

1. Subclass `BackdoorResolver` in `backdoor.py`
2. Override `resolve_register_path()` and/or `resolve_field_path()`
3. Add tests in `tests/test_backdoor.py`

## JSON register format

```json
{
  "type": "addrmap",
  "inst_name": "ip_name",
  "addr_offset": 0,
  "children": [{
    "type": "reg",
    "inst_name": "CTRL",
    "addr_offset": 0,
    "regsize": 32,
    "children": [{
      "type": "field",
      "inst_name": "enable",
      "lsb": 0, "msb": 0,
      "reset": 0,
      "sw_access": "rw",
      "woclr": 0
    }]
  }]
}
```

`sw_access="rw"` + `woclr=1` maps to `SwAccess.W1C`.
