# Architecture

## Motivation

Mixing structural spec data (field layout, reset values, access types)
with mutable runtime state (predicted value, check enable) inside a
single `RegisterField` object creates three problems:

- Cannot have multiple RAL instances with different state from one spec.
- Difficult to extend access semantics (W1C, RCLR, volatile, etc.)
  without chains of if/elif in the predictor.
- Tight coupling between predictor and spec objects, making either
  hard to test or replace in isolation.

The layered design below separates each concern so each layer can be
unit-tested on its own, one spec can back many instances, and new
access semantics plug in as a new policy rather than a predictor
rewrite.

## Layer diagram

```
                    RegisterModel (spec -- immutable-ish)
                    |   SwAccess, RegisterField, Register, RegisterBlock
                    |
                RuntimeState (per-instance mutable state)
                |   FieldState: mirrored, desired, check_enabled, dirty
                |
        RuntimePredictor + PolicyRegistry + AccessPolicy
        |   apply_write(), apply_read_side_effect(), check_on_read()
        |   volatile_policy: is_field_volatile(), check_allowed()
        |
    RuntimeRAL (cocotb integration)
    |   attach_master(), write(), read(), notify_external_write()
    |
    SafeRuntimeRAL
    |   write_field() with assess_field_rmw() safety check
    |
    IntegratedRuntimeRAL
        backdoor_resolver: BackdoorResolver / PrefixBackdoorResolver / MappingBackdoorResolver
        txn_logger: TransactionLogger (optional file output)
        dump_runtime_state(), diff_runtime_state()
```

## Key design decisions

### Spec vs state separation

`RegisterModel` holds structural truth: field positions, reset values, access types, HDL paths. This is loaded once from JSON or RDL and doesn't change during simulation.

`RuntimeState` holds per-instance mutable state: mirrored value (what the predictor thinks hardware has), desired value, check_enabled, dirty flag. Each RAL instance gets its own `RuntimeState`, so one `RegisterModel` can back multiple tile instances.

### Policy-based access semantics

`AccessPolicy` encapsulates write/read behavior per `SwAccess` type. Instead of if/else chains scattered through the predictor, all access-type logic is in `apply_write()`, `apply_read_side_effect()`, and `check_on_read()`. Adding a new access type means adding cases to one class.

### Volatile inference

`RegisterField` auto-infers `volatile=True` for RO, RCLR, and RSET fields. Volatile fields are not prediction-checked on read, since hardware may change their value at any time. This can be overridden with an explicit `volatile=True/False` parameter.

### RMW safety

`SafeRuntimeRAL.write_field()` calls `assess_field_rmw()` before performing a read-modify-write. If any non-target field has a non-RW access type (RO, W1C, WO, etc.), the RMW is blocked with a `RuntimeError`. This prevents silent corruption of status bits, interrupt flags, or write-only command fields.

### Backdoor resolution

`BackdoorResolver` separates logical register identifiers from concrete HDL paths. `PrefixBackdoorResolver` prepends an instance prefix (e.g. tile HDL path) to relative paths from the register spec. `MappingBackdoorResolver` uses explicit name-to-path dictionaries. This allows one register spec to be reused across 100+ tile instances with different HDL paths.

### Transaction logging

`TransactionLogger` is optional and zero-overhead when disabled. When enabled via `txn_log=`, it intercepts `write()`, `read()`, and `write_field()` calls and writes a detailed record to a file. Each entry includes model path, address, data, protocol, interface, status, mirror state delta, per-field breakdown, and RMW safety assessment.

### Deprecation approach

The legacy `RAL` and `Predictor` classes emit `DeprecationWarning` on instantiation (not on import). `RAL` skips the warning when instantiated via a subclass (e.g. `RuntimeRAL`). The `sync_from_legacy_model()` / `sync_to_legacy_model()` bridges keep both representations in sync during migration.

## Three tiers

1. **Tier 0 (pure Python, zero dependencies)**: `register_model.py`, `state.py`, `access_policy.py`, `runtime_predictor.py`, `predictor.py`, `checker.py`, `rmw_policy.py`, `backdoor.py`, `debug.py`, `volatile_policy.py`, `transaction_logger.py`, adapters
2. **Tier 1 (requires cocotb)**: `ral.py`, `runtime_ral.py`, `safe_runtime_ral.py`, `integrated_runtime_ral.py`, `monitor.py`
3. **Tier 2 (optional)**: `rdl_loader.py` requires `systemrdl-compiler`
