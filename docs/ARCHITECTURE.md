# Architecture Overview

## Runtime Architecture (Recommended)

```
RegisterModel (spec)
        ↓
    RuntimeState
        ↓
RuntimePredictor + AccessPolicy
        ↓
SafeRuntimeRAL
        ↓
IntegratedRuntimeRAL
        ↓        ↓
 Backdoor    Debug Tools
```

## Key Concepts

### Spec vs Runtime Separation

- RegisterModel = structure
- RuntimeState = simulation state

### Policy-Based Behavior

- AccessPolicy controls read/write semantics
- Enables extensibility (W1C, RC, etc.)

### Safety Layer

- RMW hazards are detected and blocked

### Backdoor Resolution

- Logical → physical path mapping
- Supports replicated designs

---

## Stable Path

```
RegisterModel → Predictor → RAL
```

---

## Why this matters

This architecture enables:

- multi-instance reuse
- chiplet scaling
- safer register access
- easier debugging
