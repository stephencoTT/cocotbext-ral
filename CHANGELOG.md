# Changelog

## v0.6.0

### Breaking changes: single runtime RAL class
- Consolidated the three runtime RAL classes into one. `RuntimeRAL` is now
  the single RAL class and absorbs everything the old subclasses provided:
  RuntimeState-backed prediction + front-door bus access and monitor
  (formerly `RuntimeRAL`), conservative read-modify-write safety on
  `write_field()` (formerly `SafeRuntimeRAL`), and pluggable backdoor
  resolution, debug helpers, and optional transaction logging (formerly
  `IntegratedRuntimeRAL`).
- Removed `SafeRuntimeRAL` and `cocotbext/ral/safe_runtime_ral.py`.
- Removed `IntegratedRuntimeRAL` and `cocotbext/ral/integrated_runtime_ral.py`.
- Top-level exports no longer include `SafeRuntimeRAL` or
  `IntegratedRuntimeRAL`.

### Migration
- Replace `IntegratedRuntimeRAL(...)` and `SafeRuntimeRAL(...)` with
  `RuntimeRAL(...)`. The constructor signature is unchanged from
  `IntegratedRuntimeRAL`: `RuntimeRAL(name, model, dut_handle=None,
  backdoor_resolver=None, txn_log=None)`.
- `RuntimeRAL.write_field()` now always performs the RMW safety check that
  used to require `SafeRuntimeRAL`. Code that previously relied on the bare
  `RuntimeRAL` performing an unchecked RMW will now raise `RuntimeError`
  on unsafe field writes; use `set_field_predicted()` / direct
  `runtime_state` access for raw mirror manipulation if that is intended.

### Additions
- `RuntimeRAL.notify_external_read(address)`: read-side-effect counterpart
  to `notify_external_write()`. Applies RCLR (→0) and RSET (→all-1s) read
  side-effects to the mirror without driving the bus or checking, for when
  another agent reads a read-clear / read-set register. Backed by
  `RuntimePredictor.apply_external_read()`.
- Loader access-type coverage: both the RDL and JSON loaders now map
  `woset` → `W1S`, `rclr` → `RCLR`, and `rset` → `RSET` (in addition to
  the existing `woclr` → `W1C` and plain `rw`/`r`/`w`). The JSON loader
  accepts either boolean flags (`woset`/`rclr`/`rset`) or the
  `onwrite`/`onread` string forms. Precedence: write side-effects win over
  read side-effects, which win over the plain access type.
- New example `examples/search_and_bulk.py` demonstrating `find_registers`
  / `find_fields` / `group_by` and the `write_pattern` / `write_field_pattern`
  / `read_pattern` / `write_many` bulk APIs over a replicated DMA0..DMA7 map.

### cocotb 2.x compatibility
- Now works on both cocotb 1.x and cocotb 2.x. cocotb 2.0 renamed the
  `units=` keyword to `unit=` on `Timer` / `get_sim_time`; both call sites
  now pass the unit positionally, which is valid on both lines.
- `RuntimeRAL._resolve_hdl_value` (backdoor reads) handles cocotb 2.x
  `LogicArray` values in addition to 1.x `BinaryValue`, mapping X/Z bits to
  0 via the binary string instead of the removed `BinaryValue.n_bits` API.
- Under cocotb 2.x you need a cocotb-2.x-compatible `cocotbext-axi` build
  (see README "cocotb 1.x and 2.x").

### Tooling / packaging
- Ships a `py.typed` marker so downstream `mypy` / editors consume the
  type hints.
- `ruff` and `mypy` are now part of the `dev` extra and run in CI; the
  package is lint-clean and type-checks cleanly.
- CI (`.github/workflows/test.yml`): unit tests now install the `rdl`
  extra so the SystemRDL loader path is exercised, plus a lint/type-check
  job (`ruff` + `mypy`).

### Modeling & access features
- **Field enumerations**: `RegisterField(enum={...})` with
  `enum_value(name)` / `enum_name(value)`. `write_field` / `set_field`
  accept a symbolic name; `read_field_name()` returns it. RDL loader maps
  the `encode` property; JSON loader accepts `encode`/`enum`.
- **Reset domains**: `RegisterField(resets={"soft": ...})`,
  `reset_value_for(domain)`, `Register.reset_domains()`, and
  `RuntimeRAL.reset(domain=...)` for soft/secondary resets.
- **Wide registers on narrow buses**: registers wider than the bus data
  width split into multiple beats on APB (`RuntimeRAL(data_width=...)`).
- **Bus-response checking**: `RuntimeRAL(check_response=True)` flags AXI
  error responses (SLVERR/DECERR); `raise_on_bus_error` chooses raise vs log.
- **Byte-strobe partial writes**: `write_field(..., partial=True)` skips the
  RMW for byte-aligned fields, driving only those bytes via byte-enables.
- **Pre/post callbacks**: `add_callback("pre_write"|"post_write"|"pre_read"
  |"post_read", fn)` hooks fired around bus access.
- **Memory burst**: `Memory.write_block()` / `read_block()`.
- **Multiple address maps**: `RuntimeRAL(address_offset=...)` drives one
  spec through several physical maps (one RAL per map, independent state).
- **SystemRDL `counter`** fields load as volatile.
- New example `examples/backdoor_tiled.py` (address offset + backdoor across
  a tile grid).

## v0.3.1

### Breaking changes: legacy path removed
- Removed the legacy `RAL` class; `RuntimeRAL` is now the standalone base
  and owns front-door bus access, backdoor, monitor attach, bulk / pattern
  APIs, and all check-state helpers.
- Removed the legacy `Predictor` class and `cocotbext/ral/predictor.py`.
  `PredictionResult` / `FieldResult` now live in
  `cocotbext.ral.runtime_predictor`. Re-exports from the top-level
  `cocotbext.ral` package are unchanged.
- Removed legacy state attributes on spec objects:
  `RegisterField.predicted_value`, `RegisterField.check_enabled`,
  `RegisterField.reset()`, `Register.predicted_value`, `Register.reset()`,
  `RegisterBlock.reset()`, `RegisterModel.reset()`. All mutable mirror
  state now lives exclusively in `RuntimeState`.
  `RegisterField.is_checkable_on_read` is retained as a pure spec-level
  predicate (access type + volatile), no longer consults per-field
  `check_enabled` -- the runtime layer gates that separately.
- Removed `RuntimeState.sync_from_legacy_model()` and
  `sync_to_legacy_model()` plus the calls from `RuntimePredictor`.
- Top-level exports no longer include `RAL` or `Predictor`.

### Fixes
- `RuntimeRAL.reset()` now correctly resets the mirror in `RuntimeState`.
  The previous behavior only reset legacy `RegisterField.predicted_value`
  (which no longer exists), leaving the runtime mirror stale.

### Additions
- `RuntimeRAL.disable_check_all()` / `enable_check_all()`: one-call toggle
  of prediction checking across every register in the model, for users
  treating the RAL purely as access abstraction + search.

## v0.3.0

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
