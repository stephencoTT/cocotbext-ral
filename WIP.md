# Work-in-Progress / Follow-ups

Captured from a design audit; not scheduled yet. Ordered roughly by value.

## High value

### 1. Continuous integration

Currently nothing verifies the 164 pytest unit tests on push / PR. A small
GitHub Actions workflow (`pytest` on a Python 3.8-3.11 matrix, run on
`push` and `pull_request` against `main`) would catch regressions before
merge and give the README a status badge.

Suggested layout: `.github/workflows/ci.yml`, steps = checkout, setup
python, `pip install -e .[dev,rdl]`, `pytest -q`.

### 2. Mirror-update API asymmetry

`notify_external_write(addr, data)` exists for SW-style writes from
another agent, but there is no `notify_external_read(addr)` counterpart.
For fields with read side-effects (`RCLR`, `RSET`), an external read
changes the hardware state, so the RAL mirror needs to know. The current
workaround is `set_predicted`, which ignores policy.

Proposed addition:

```python
def notify_external_read(self, address: int) -> None:
    """Tell the mirror that an external agent just read this register.
    Applies the same read side-effects (RCLR -> 0, RSET -> all-1s) that
    the RAL's own ``read()`` would apply, without driving the bus."""
```

Drop-in to `RuntimeRAL`; reuses `AccessPolicy.apply_read_side_effect()`.

### 3. SystemRDL loader coverage

`cocotbext/ral/adapters/rdl_loader.py::_map_sw_access` currently handles:
- `sw=rw` + `woclr` -> `W1C`
- `sw=rw` -> `RW`
- `sw=r` -> `RO`
- `sw=w` -> `WO`

Missing mappings that real SystemRDL designs use:
- `woset` -> `W1S`
- `rclr` property -> `RCLR`
- `rset` property -> `RSET`
- Composite `intr`/`mask`/`enable`/`haltmask`/`haltenable` groups.
- `counter` property (incr/decr semantics).
- Array elaboration already works via `unroll=True`, but explicit tests
  would help.

Scope is clearly bounded: one branch per property in the mapper plus one
fixture per mapping in `tests/`.

## Medium value

### 4. `disable_check_all()` convenience

Today users can disable checking per register or per field, but there is
no single call to turn off prediction checking across the whole model.
The workaround is:

```python
for reg in model.all_registers():
    ral.disable_check(reg.hierarchical_name)
```

A one-liner would be ergonomic and would make the "use the RAL just for
access abstraction and search, not for checking" use case first-class.
`enable_check_all()` is the obvious pair. Implement on `RuntimeRAL` and
forward to `RuntimeState`.

### 5. Example for search / bulk APIs

`examples/` has `basic_runtime_ral.py` and `axil_cocotb_demo.py` but
nothing showing the new `find_registers` / `write_pattern` /
`write_many` APIs. A 30-40 line `examples/search_and_bulk.py` building a
small `DMA0..DMA7` model and driving bulk programming would make the
feature tangible for readers.

## Low value / polish

### 6. `.gitignore`

Not ignoring `out/`, `.ttem/`, `*.egg-info/`, `__pycache__/`,
`.pytest_cache/`, `build/`, `dist/`, `.venv/`. These show up on every
`git status`.

### 7. `Development Status` classifier

`pyproject.toml` says `Development Status :: 3 - Alpha`. If the package
is actively used by downstream verification workspaces (edc_tb, qs5,
etc.), `4 - Beta` is closer to reality.
