# Deprecation and Migration Plan

This file exists because the repository currently contains both a legacy RAL path and a newer runtime-backed path.

## Recommended path going forward

Use the runtime-backed stack for new code:

- `IntegratedRuntimeRAL`
- `SafeRuntimeRAL`
- `RuntimeRAL`
- `RuntimePredictor`
- `RuntimeState`

## Legacy path

The following remain supported for compatibility but are now considered legacy design paths:

- `RAL`
- `Predictor`
- direct mutation of `RegisterField.predicted_value`
- direct mutation of `RegisterField.check_enabled`

## Migration mapping

| Legacy | Recommended replacement |
|--------|--------------------------|
| `RAL` | `IntegratedRuntimeRAL` |
| `Predictor` | `RuntimePredictor` |
| `RegisterField.predicted_value` | `RuntimeState` field mirrored value |
| direct HDL path strings | backdoor resolvers |

## Temporary repository state

The top-level `README.md` still needs to be overwritten with the new runtime-focused version, and package-level deprecation warnings still need to be wired into the legacy modules. The GitHub connector available in this session was able to add new files but did not expose a direct overwrite path for existing files.

Until that overwrite is completed, treat the files below as the current source of truth for the new architecture:

- `DESIGN.md`
- `docs/ARCHITECTURE.md`
- `examples/basic_runtime_ral.py`
- `examples/axil_cocotb_demo.py`
- `cocotbext/ral/experimental.py`
