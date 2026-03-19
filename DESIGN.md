# cocotbext-ral — Data-Driven Architecture (v0 refactor)

## Problem Statement

The original implementation mixed:
- **spec data** (field layout, reset, access)
- **runtime state** (predicted value, check enable)

inside `RegisterField`.

This creates problems:
- cannot have multiple RAL instances with different state
- difficult to extend semantics (W1C, RC, volatile, etc.)
- tight coupling between predictor and spec objects

---

## New Architecture (Incremental)

We introduce a **runtime state layer**:

```
RegisterModel (spec, immutable-ish)
        ↓
RuntimeState
        ↓
Predictor / RAL
```

### Spec Layer
- `RegisterModel`
- `Register`
- `RegisterField`

Contains:
- structure
- reset values
- access types

### Runtime Layer
- `RuntimeState`
- `RegisterState`
- `FieldState`

Contains:
- mirrored value
- desired value
- check enable
- dirty flag

---

## Access Policy Engine

All field behavior is routed through:

```
AccessPolicy.apply_write()
AccessPolicy.check_on_read()
```

This avoids scattering logic like:

```
if sw_access == ...
```

across the codebase.

---

## Migration Strategy

We maintain compatibility by:

- syncing runtime → legacy fields
- syncing legacy → runtime (initialization)

This allows:

- existing APIs to work unchanged
- gradual refactor of predictor + RAL

---

## Next Steps

1. Move Predictor fully to RuntimeState
2. Replace direct field mutation in RAL
3. Add richer access semantics
4. Add backdoor abstraction layer

---

## Long-Term Vision

- JSON/RDL → spec
- runtime state per instance
- pluggable policy engine
- cocotb-native lightweight RAL

This keeps:

- UVM-like *usage*
- Pythonic *implementation*
