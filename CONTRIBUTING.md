# Contributing to cocotbext-ral

Thanks for contributing.

## Development setup

Clone the repo, create a virtual environment, install editable dependencies, and run the tests.

## Design principles

This project is evolving toward a data-driven runtime architecture:

- register specs remain structural truth
- runtime state holds mirrored and check state
- access semantics live in policy helpers
- backdoor mapping is resolved at integration time

Please prefer incremental changes that preserve the stable API unless the change is explicitly for the experimental runtime path.

## Pull request guidelines

- keep changes focused
- add or update tests for behavioral changes
- prefer conservative semantics over surprising magic
- document new access policy behavior clearly
- include examples when adding a new public feature

## Helpful contribution areas

- richer CSR access semantics
- JSON and SystemRDL metadata extensions
- cocotb integration tests
- monitor robustness for interleaved AXI traffic
- documentation and examples
