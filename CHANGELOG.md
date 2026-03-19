# Changelog

## v0.2.0

### 🚀 Major Features
- Introduced runtime-backed RAL architecture (`RuntimeRAL`, `SafeRuntimeRAL`, `IntegratedRuntimeRAL`)
- Clean separation of register spec vs runtime state
- Added access policy framework for extensible CSR semantics

### 🛡️ Safety Improvements
- Safe field write handling (prevents RMW corruption)
- Explicit prediction vs check separation

### 🔌 Integration Enhancements
- Backdoor resolver abstraction for scalable designs (chiplets, tiles)
- Improved cocotb AXI/APB integration examples

### 📚 Documentation
- Rewritten README with runtime-first positioning
- Added architecture documentation (`docs/ARCHITECTURE.md`)
- Added working examples (`examples/`)

### ⚠️ Deprecations
- `RAL` marked as legacy API (still supported)
- `Predictor` marked as legacy (use runtime predictor instead)

### 🧠 Internal Improvements
- Data-driven runtime state model
- Cleaner separation of responsibilities across layers

---

## v0.1.0

- Initial release
- Basic register model + predictor
- AXI/APB support
