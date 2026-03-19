# API Documentation

This documentation is split into smaller files so readers can navigate by topic instead of scrolling through one giant page.

That is a common and sensible approach for Python packages once the API surface grows beyond a single short reference page.

## Start here

- [Core model](api/CORE_MODEL.md)
- [Legacy / stable API](api/LEGACY_API.md)
- [Runtime-backed API](api/RUNTIME_API.md)
- [Backdoor, debug, and loaders](api/INTEGRATION_AND_LOADERS.md)

## Recommended path for new code

For new projects, prefer:

- `IntegratedRuntimeRAL`
- `SafeRuntimeRAL`
- `RuntimeRAL`
- `RuntimePredictor`
- `RuntimeState`

## Why split the docs?

Splitting by topic helps with:

- easier navigation on GitHub
- clearer mental model for readers
- lower maintenance cost when a single subsystem changes
- future migration to MkDocs / Sphinx if desired

## Minimal example

```python
from cocotbext.ral import IntegratedRuntimeRAL
from cocotbext.ral.adapters import load_json

model = load_json("registers.json")
ral = IntegratedRuntimeRAL("my_ip", model)
```
