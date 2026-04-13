# CLAUDE.md

This file provides guidance to Claude Code when working with the cocotbext-ral project.

## What this project is

`cocotbext-ral` is a Python-native Register Abstraction Layer (RAL) for cocotb hardware verification. It provides UVM-like register modeling, access-type-aware prediction, and automated checking -- all in pure Python.

## Project structure

```
cocotbext/ral/
  register_model.py    # Core: SwAccess, RegisterField, Register, RegisterBlock, RegisterModel
  state.py             # Runtime: FieldState, RegisterState, RuntimeState
  access_policy.py     # Runtime: AccessPolicy, PolicyRegistry
  runtime_predictor.py # Runtime: RuntimePredictor (recommended predictor)
  predictor.py         # Legacy: Predictor (deprecated, still supported)
  checker.py           # Checker scoreboard
  ral.py               # Legacy: RAL class (requires cocotb)
  runtime_ral.py       # Runtime: RuntimeRAL (requires cocotb)
  safe_runtime_ral.py  # Runtime: SafeRuntimeRAL (requires cocotb)
  integrated_runtime_ral.py  # Runtime: IntegratedRuntimeRAL (requires cocotb)
  backdoor.py          # BackdoorResolver, PrefixBackdoorResolver, MappingBackdoorResolver
  rmw_policy.py        # RMW safety assessment (assess_field_rmw)
  volatile_policy.py   # Volatile field helpers (is_field_volatile, check_allowed, VolatileMixin)
  debug.py             # dump_state(), diff_state()
  monitor.py           # ApbRalMonitor, AxiLiteRalMonitor, AxiRalMonitor (requires cocotb)
  version.py           # __version__
  experimental.py      # Stable import point for runtime APIs
  adapters/
    json_loader.py     # load_json() for RDL-generated JSON
    rdl_loader.py      # load_rdl() for SystemRDL files
tests/                 # pytest unit tests (136 tests)
examples/              # Usage examples
docs/                  # Architecture and API documentation
```

## Architecture layers

The codebase has three tiers:

1. **Tier 0 (pure Python, zero dependencies)**: `register_model.py`, `state.py`, `access_policy.py`, `runtime_predictor.py`, `predictor.py`, `checker.py`, `rmw_policy.py`, `backdoor.py`, `debug.py`, `volatile_policy.py`, adapters
2. **Tier 1 (requires cocotb)**: `ral.py`, `runtime_ral.py`, `safe_runtime_ral.py`, `integrated_runtime_ral.py`, `monitor.py`
3. **Tier 2 (optional)**: `rdl_loader.py` requires `systemrdl-compiler`

Cocotb-dependent imports are guarded with `try/except ImportError` in `__init__.py`.

## Class hierarchy

```
IntegratedRuntimeRAL   (backdoor resolver + debug helpers)
  -> SafeRuntimeRAL    (RMW safety checking)
    -> RuntimeRAL      (RuntimeState-backed prediction)
      -> RAL           (legacy: front-door + backdoor + monitors + Checker)
```

## Key design decisions

- **Spec/state separation**: `RegisterModel` holds structural truth (immutable-ish). `RuntimeState` holds per-instance mutable state (mirrored, desired, check_enabled, dirty). This allows one model to back many tile instances.
- **Policy-based access semantics**: `AccessPolicy` encapsulates write/read behavior per `SwAccess` type, rather than if/else chains.
- **Volatile inference**: `RegisterField` auto-infers `volatile=True` for RO, RCLR, RSET fields (overridable via explicit `volatile=` parameter).
- **Deprecation warnings on instantiation, not import**: Legacy `Predictor` and `RAL` emit `DeprecationWarning` only when constructed, not when the module is imported. `RAL` skips the warning when instantiated via a subclass (e.g. `RuntimeRAL`).
- **Legacy bridge**: `RuntimeState.sync_from_legacy_model()` / `sync_to_legacy_model()` keep both representations in sync during migration.

## Running tests

```bash
python -m pytest tests/ -v
```

All 136 tests should pass. Tests are pure Python (no cocotb simulation needed). The cocotb-dependent classes (RAL, monitors) are not unit-tested because they require a live simulation.

## Common development tasks

### Adding a new SwAccess type

1. Add the value to `SwAccess` enum in `register_model.py`
2. Add write behavior in `AccessPolicy.apply_write()` in `access_policy.py`
3. Add read side-effect in `AccessPolicy.apply_read_side_effect()` in `access_policy.py`
4. Add to `check_on_read()` checkable set if applicable
5. Update `_VOLATILE_ACCESS_TYPES` in `RegisterField` if inherently volatile
6. Handle in legacy `Predictor.predict_write()` / `predict_read()` in `predictor.py`
7. Add tests in `tests/test_runtime_predictor_comprehensive.py` and `tests/test_access_policies.py`

### Adding a new backdoor resolver

1. Subclass `BackdoorResolver` in `backdoor.py`
2. Override `resolve_register_path()` and/or `resolve_field_path()`
3. Add tests in `tests/test_backdoor.py`

### Modifying volatile behavior

- Default volatile inference is in `RegisterField.__init__()` via `_VOLATILE_ACCESS_TYPES`
- The `volatile_policy.py` module provides `is_field_volatile()` and `check_allowed()` functions used by `AccessPolicy.check_on_read()`
- The `RegisterField.is_checkable_on_read` property is used by the legacy `Predictor`

## JSON register format

The JSON loader (`load_json()`) expects RDL-generated JSON with this structure:

```json
{
  "type": "addrmap",
  "inst_name": "ip_name",
  "addr_offset": 0,
  "children": [
    {
      "type": "reg",
      "inst_name": "CTRL",
      "addr_offset": 0,
      "regsize": 32,
      "children": [
        {
          "type": "field",
          "inst_name": "enable",
          "lsb": 0,
          "msb": 0,
          "reset": 0,
          "sw_access": "rw",
          "woclr": 0
        }
      ]
    }
  ]
}
```

The `woclr` flag controls W1C mapping: `sw_access="rw"` + `woclr=1` maps to `SwAccess.W1C`.

## Integration with Quasar SoC

This library is designed to integrate with the Quasar SoC cocotb testbench. Key integration points:

- **Register definitions**: Quasar has RDL and JSON register files in `meta/registers/`. The `load_json()` adapter needs a thin wrapper to handle Quasar's `safe_registers` JSON format.
- **Access methods**: Quasar uses NOC, SMN, and JTAG access methods (not raw AMBA). Custom frontdoor adapters wrapping `AccessMethodRegistry` methods would feed into RAL's master interface.
- **Multi-instance**: Quasar has 100+ tiles. Use one `RegisterModel` per tile type with separate `RuntimeState` instances per tile coordinate.
- **Backdoor paths**: Quasar's `chiplet_hierarchy` package (`get_tile_path()`, `get_smu_path()`) maps to `PrefixBackdoorResolver`.
