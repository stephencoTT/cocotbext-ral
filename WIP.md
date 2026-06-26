# Work-in-Progress / Follow-ups

Captured from a design audit; not scheduled yet. Ordered roughly by value.
Completed items are listed under "Done"; see the CHANGELOG for detail.

## High value

### 1. Simulator-in-the-loop test

All current tests are pure Python; the cocotb bus path (`_protocol_write` /
`_protocol_read`), the monitors, and backdoor HDL access are never exercised
against a real DUT in a simulator. A small AXI-Lite smoke test (an
`AxiLiteMaster` + `AxiLiteRam` over a wiring-only DUT, driven by `RuntimeRAL`,
asserting clean prediction) run under Icarus Verilog would cover the highest-
risk, currently-unverified code. Deferred because no simulator is available in
the dev/CI environment used so far.

## Medium value

### 2. Interrupt aggregation modeling

SystemRDL `intr` fields already load with the right access type (their
`onwrite=woclr` maps to `W1C`), and `counter` fields load as volatile. What
is *not* modeled is the aggregation tree -- an `intr` register's summary bit
computed from masked sub-interrupts (`mask` / `enable` / `haltmask` /
`haltenable`). This is largely hardware behavior the RAL observes via reads
rather than predicts, so it would be a new, optional layer (a derived/computed
field) rather than a change to the existing access policies. Scope it before
committing.

## Low value / polish

### 3. `Development Status` classifier

`pyproject.toml` says `Development Status :: 3 - Alpha`. If the package
is in active downstream use, `4 - Beta` is closer to reality.

---

## Done (kept for reference)

- **Continuous integration** — `.github/workflows/test.yml` runs `pytest`
  on a Python 3.9-3.13 matrix on push / PR to `main`, installing the
  `rdl` extra so the SystemRDL loader path is exercised.
- **Lint + type-check in CI** — `ruff` and `mypy` run as a CI job; the
  package is lint-clean and type-checks cleanly.
- **`py.typed`** — ships the PEP 561 marker so downstream `mypy` / editors
  consume the type hints.
- **cocotb 2.x support** — library works on cocotb 1.x and 2.x; see CHANGELOG.
- **Single runtime RAL class** — `RuntimeRAL` consolidates the former
  `RuntimeRAL` / `SafeRuntimeRAL` / `IntegratedRuntimeRAL` chain (v0.6.0).
- **`notify_external_read()`** — read-side-effect counterpart to
  `notify_external_write()` (v0.6.0).
- **Access-type side-effect loader coverage** — `woset`/`rclr`/`rset`
  (and `woclr`) map in both the RDL and JSON loaders (v0.6.0).
- **Field enumerations** — `enum=` on `RegisterField`, symbolic write/read,
  loader support (v0.6.0).
- **Reset domains** — per-field named resets + `reset(domain=...)` (v0.6.0).
- **Wide registers on narrow buses** — APB multi-beat split via
  `data_width=` (v0.6.0).
- **Bus-response checking** — `check_response=` flags AXI SLVERR/DECERR
  (v0.6.0).
- **Byte-strobe partial writes** — `write_field(..., partial=True)` (v0.6.0).
- **Pre/post callbacks** — `add_callback(...)` hooks around bus access
  (v0.6.0).
- **Memory burst** — `Memory.write_block()` / `read_block()` (v0.6.0).
- **Multiple address maps** — `address_offset=` per RAL (v0.6.0).
- **`disable_check_all()` / `enable_check_all()`** — on `RuntimeRAL`.
- **`.gitignore`** — covers build/venv/cache artifacts.
- **Examples** — `basic_runtime_ral.py`, `axil_cocotb_demo.py`,
  `search_and_bulk.py`, `backdoor_tiled.py`.
