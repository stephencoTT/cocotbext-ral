# Changelog

## Unreleased

### Search and bulk APIs
- `RegisterModel.find_registers(name=, regex=, access=, hierarchy_prefix=, predicate=)`
  returns matching registers sorted by address.
- `RegisterModel.find_fields(...)` returns `(register, field)` tuples with
  the same filter kwargs plus `reg_name=`.
- `RegisterModel.group_by(key_fn)` groups registers by an arbitrary key
  (e.g. instance prefix for `DMA0..DMA7`).
- `RAL.write_pattern(pattern, value)`, `write_field_pattern`, and
  `read_pattern` drive transactions across every matched register.
- `RAL.write_many(mapping, sort=True, best_effort=False)` writes a dict
  of heterogeneous registers in one call, address-sorted by default, with
  fail-fast or best-effort semantics.
- Patterns are fnmatch globs unless a `regex=` kwarg is passed. Matching
  is case-sensitive against the register's hierarchical name.

### Transaction log format
- `write_field` RMW sequences now render as a single numbered `WRITE_FIELD`
  entry with the internal bus read + write-back nested under a
  `Bus traffic:` section. Previously each field write produced three
  separate log entries (READ, WRITE, WRITE_FIELD), making the log verbose
  and the TXN count misleading. The change applies whenever transaction
  logging is enabled; no opt-in required.
- Added `TransactionLogger.begin_rmw()` / `end_rmw()` for wrapping custom
  RMW sequences. `IntegratedRuntimeRAL.write_field()` uses them internally.
- `Transaction` dataclass gained a `substeps: List[Transaction]` field
  holding the nested bus-level children of an RMW entry.

### Documentation
- Added a "Mirror update modes" table in `docs/api/RUNTIME_API.md`
  clarifying the distinction between `write()`, `notify_external_write()`,
  and `set_predicted()` / `set_field_predicted()`: bus traffic vs. no bus
  traffic, and access-policy-aware vs. raw mirror overwrite.

## v0.2.0

### Major Features
- Introduced runtime-backed RAL architecture (`RuntimeRAL`, `SafeRuntimeRAL`, `IntegratedRuntimeRAL`)
- Clean separation of register spec vs runtime state
- Added access policy framework for extensible CSR semantics
- Full access-type coverage: RW, RO, WO, W1C, W1S, RCLR, RSET
- Optional transaction file logging (`TransactionLogger`) with per-transaction detail
- Explicit `interface=` parameter on `attach_master()` for HDL path identification

### Bug Fixes
- Fixed `Predictor.predict_read()` not populating `error_messages` on mismatch
- Fixed `RegisterField.is_volatile` not inferring volatility from access type (RO, RCLR, RSET now default to volatile)
- Fixed deprecation warning firing at import time instead of instantiation
- Fixed `RAL` deprecation warning firing when instantiated via subclass (`RuntimeRAL`)
- Fixed `version.py` still reporting 0.1.0

### Safety Improvements
- Safe field write handling (prevents RMW corruption)
- Explicit prediction vs check separation

### Integration Enhancements
- Integrated `VolatileMixin` into `AccessPolicy.check_on_read()` via `volatile_policy` module functions
- Backdoor resolver abstraction for scalable designs (chiplets, tiles)
- Improved cocotb AXI/APB integration examples

### Test Coverage
- Added comprehensive tests for RuntimePredictor (all access types: RW, RO, WO, W1C, W1S, RCLR, RSET)
- Added tests for RuntimeState, RegisterState, FieldState
- Added tests for RMW safety assessment (`assess_field_rmw`)
- Added tests for BackdoorResolver, PrefixBackdoorResolver, MappingBackdoorResolver
- Added tests for debug helpers (`dump_state`, `diff_state`)
- Added tests for volatile policy functions and VolatileMixin
- Total: 136 tests, all passing (up from 52 with 3 failures)

### Documentation
- Rewritten README with runtime-first positioning and access-type reference table
- Added `CLAUDE.md` for AI-assisted development guidance
- Added architecture documentation (`docs/ARCHITECTURE.md`)
- Added working examples (`examples/`)

### Deprecations
- `RAL` marked as legacy API (still supported, warns on direct instantiation)
- `Predictor` marked as legacy (warns on instantiation, use RuntimePredictor instead)

### Internal Improvements
- Data-driven runtime state model
- Cleaner separation of responsibilities across layers

---

## v0.1.0

- Initial release
- Basic register model + predictor
- AXI/APB support
