# Spec Delta

## ADDED Requirements

### Requirement: Source execution agrees with the reviewed Python pin
The supported `uv run --script longform.py` entry point SHALL constrain Python to the reviewed minor through authoritative `cpython@3.13` and PEP 723 `requires-python = ">=3.13,<3.14"`. The metadata SHALL allow patch updates without file edits and SHALL reject 3.12 and 3.14+. Automated checks SHALL detect disagreement between the minor pin and metadata.

#### Scenario: Run the launcher from another directory
- **WHEN** a maintainer runs `uv run --script /absolute/path/to/longform.py --help` from outside the checkout with a different default Python
- **THEN** it provisions or uses an allowed 3.13 patch and prints the existing help with exit 0
- **AND** if an allowed interpreter cannot be provisioned it exits nonzero without running the application on another minor

#### Scenario: Request an incompatible source interpreter
- **WHEN** the source launcher is invoked through uv with an explicit Python 3.12 or 3.14+ request incompatible with its minor-range metadata
- **THEN** the invocation exits nonzero before executing application commands or writing project files

#### Scenario: Source metadata drifts from the authoritative pin
- **WHEN** a maintainer changes either the authoritative pin or source Python metadata without updating the other
- **THEN** automated regression coverage fails and identifies the disagreement

#### Scenario: A different allowed patch is selected
- **WHEN** source execution resolves to a newer available 3.13 patch
- **THEN** the unchanged launcher metadata accepts it without a patch-specific pin or reviewed two-file update

### Requirement: Project checks enforce the reviewed CPython minor throughout
`scripts/check.sh` SHALL run syntax, CLI smoke, standalone-test, and source-test phases on CPython 3.13.x, matching the build's minor policy. It SHALL print the verified full version and fail on missing uv, invalid minor pin, wrong implementation/minor, or provisioning failure. Host Python, active environments, and conflicting `UV_PYTHON` SHALL NOT silently change the selected implementation/minor.

#### Scenario: Run checks with a different host Python
- **WHEN** a maintainer runs `./scripts/check.sh` with a conflicting host Python, active environment, or `UV_PYTHON`
- **THEN** a successful run prints `== python: CPython 3.13.<patch>` with the actual patch number, followed by the existing phase markers and passing suites
- **AND** syntax compilation, CLI smoke, both pytest processes, their Python subprocesses, and the standalone build use CPython 3.13.x

#### Scenario: Checks provision a newer patch automatically
- **WHEN** the provisioning resolver offers a newer 3.13 patch than the installed one and checks run
- **THEN** checks resolve that latest available patch without changing the minor pin or source metadata
- **AND** they report the actual full version rather than requiring a fixed patch value

#### Scenario: Required interpreter cannot be verified
- **WHEN** uv is missing, the pin is missing, patch-specific or otherwise malformed, provisioning fails, or verification returns another implementation/minor
- **THEN** checks exit nonzero with an actionable diagnostic before syntax compilation or any suite can pass on a fallback interpreter

#### Scenario: Drift and crash regressions remain mandatory
- **WHEN** the maintainer runs the check entry point
- **THEN** it executes the interpreter-selection, source-metadata, artifact-reuse, and existing Qt/None-reference regression coverage
- **AND** failures propagate to a nonzero check result without skipped frozen or offscreen tests or weakened network guards
