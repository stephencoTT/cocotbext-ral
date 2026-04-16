# Contributing

## Development setup

```bash
git clone https://github.com/stephencoTT/cocotbext-ral.git
cd cocotbext-ral
git checkout refactor/data-driven-state-v0
pip install -e .[dev]
pytest
```

## Design principles

- Register specs are structural truth (immutable-ish)
- Runtime state holds mutable per-instance data
- Access semantics live in policy helpers
- Backdoor mapping is resolved at integration time
- Transaction logging is optional and zero-overhead when disabled

## Adding a new SwAccess type

1. Add value to `SwAccess` enum in `register_model.py`
2. Add write behavior in `AccessPolicy.apply_write()`
3. Add read side-effect in `AccessPolicy.apply_read_side_effect()`
4. Add to `check_on_read()` checkable set if applicable
5. Update `_VOLATILE_ACCESS_TYPES` in `RegisterField` if inherently volatile
6. Add tests in `tests/test_runtime_predictor_comprehensive.py` and `tests/test_access_policies.py`

## Pull request guidelines

- Keep changes focused
- Add or update tests for behavioral changes
- Include examples when adding a new public feature
- Run `pytest` -- all 146 tests must pass
