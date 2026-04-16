# Design Notes

## Problem

Mixing structural spec data (field layout, reset values, access types) with mutable runtime state (predicted value, check enable) inside `RegisterField` creates problems:

- Cannot have multiple RAL instances with different state from one spec
- Difficult to extend access semantics (W1C, RCLR, volatile, etc.)
- Tight coupling between predictor and spec objects

## Solution

Separate spec from state:

```
RegisterModel (spec -- immutable-ish)
        |
RuntimeState (per-instance mutable state)
        |
RuntimePredictor + AccessPolicy (policy-driven behavior)
        |
IntegratedRuntimeRAL (cocotb integration + backdoor + txn log)
```

### Spec layer

`RegisterModel`, `Register`, `RegisterField` hold structure, reset values, access types. Loaded once from JSON or RDL.

### Runtime layer

`RuntimeState` contains `RegisterState` -> `FieldState` (mirrored, desired, check_enabled, dirty). Each RAL instance gets its own `RuntimeState`.

### Policy layer

`AccessPolicy` encapsulates per-SwAccess write/read behavior. `VolatileMixin` handles volatile field detection. `assess_field_rmw()` validates RMW safety.

### Integration layer

`IntegratedRuntimeRAL` ties everything together with cocotb bus masters, backdoor resolvers, and optional transaction logging.

## Completed

- Runtime state separation with sync bridges
- Full access-type coverage (RW, RO, WO, W1C, W1S, RCLR, RSET)
- Policy-based access semantics
- Volatile inference from access type
- RMW safety assessment
- Backdoor resolver hierarchy (Base, Prefix, Mapping)
- Transaction file logging
- 146 unit tests
