# Spec Delta

## ADDED Requirements

### Requirement: Source execution agrees with the reviewed Python pin
The supported `uv run --script longform.py` entry point SHALL select the repository's reviewed exact Python patch version, initially 3.13.15, rather than an open-ended lower bound. The source metadata SHALL agree with the authoritative CPython pin, and automated checks SHALL detect disagreement. Unavailable or incompatible requested versions SHALL fail rather than run a different patch.

#### Scenario: Run the launcher from another directory
- **WHEN** a maintainer runs `uv run --script /absolute/path/to/longform.py --help` from outside the checkout with a different default Python
- **THEN** it provisions or uses the exact pinned release and prints the existing help with exit 0
- **AND** if the pinned interpreter cannot be provisioned it exits nonzero without running the application on a substitute

#### Scenario: Request an incompatible source interpreter
- **WHEN** the source launcher is invoked through uv with an explicit interpreter request incompatible with its exact Python metadata
- **THEN** the invocation exits nonzero before executing application commands or writing project files

#### Scenario: Source metadata drifts from the authoritative pin
- **WHEN** a maintainer changes either the authoritative pin or source Python metadata without updating the other
- **THEN** automated regression coverage fails and identifies the disagreement

### Requirement: Project checks use one exact interpreter throughout
`scripts/check.sh` SHALL run syntax, CLI smoke, standalone-test, and source-test phases on the same pinned ordinary CPython used for freezing. It SHALL print the verified interpreter before these phases and fail on missing uv, invalid pin, wrong interpreter, or unavailable pinned Python. Host Python, active environments, and conflicting `UV_PYTHON` SHALL NOT silently change the selection.

#### Scenario: Run checks with a different host Python
- **WHEN** a maintainer runs `./scripts/check.sh` with a conflicting host Python, active environment, or `UV_PYTHON`
- **THEN** a successful run prints `== python: CPython 3.13.15` followed by the existing phase markers and passing suites
- **AND** syntax compilation, CLI smoke, both pytest processes, their Python subprocesses, and the standalone build use the pin

#### Scenario: Required interpreter cannot be verified
- **WHEN** uv is missing, the pin is missing or malformed, provisioning fails, or verification returns a different interpreter
- **THEN** checks exit nonzero with an actionable diagnostic before syntax compilation or any suite can pass on a fallback interpreter

#### Scenario: Drift and crash regressions remain mandatory
- **WHEN** the maintainer runs the check entry point
- **THEN** it executes the interpreter-selection, source-metadata, artifact-reuse, and existing Qt/None-reference regression coverage
- **AND** failures propagate to a nonzero check result without skipped frozen or offscreen tests or weakened network guards
