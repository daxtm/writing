# offline-regression Specification

## Purpose

Give CLI maintainers repeatable regression feedback without private writing projects, credentials, or live API requests.

## Requirements

### Requirement: Regression checks run without external services
The regression suite SHALL use synthetic data and temporary project files, require
no real API credentials, and make no live HTTP requests. Dependency installation
is separate from offline test execution.

#### Scenario: Run with no credentials or network service
- **WHEN** the installed suite runs with API credential environment variables removed and external HTTP connections blocked
- **THEN** all regression tests pass using local fixtures and mocked responses
- **AND** no private sample project or third-party preset is read

#### Scenario: An unexpected request is rejected
- **WHEN** a test attempts an HTTP request outside its configured mock handler
- **THEN** the test fails immediately rather than contacting an external service

### Requirement: The suite is discoverable from the repository root
The command `uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' pytest -q tests` SHALL discover and run the regression suite from the repository root without installing the CLI as a package. Model and CLI tests SHALL require neither a display nor GUI imports; widget cases SHALL execute in an isolated subprocess using `QT_QPA_PLATFORM=offscreen`.

#### Scenario: Run the documented test command
- **WHEN** a maintainer runs the documented command in a checkout with Python 3.12+ and uv available
- **THEN** tests are collected, the passing summary reports a nonzero number of passed tests, and the command exits 0
- **AND** widget cases actually execute offscreen without requiring a Wayland/X11 session

#### Scenario: Missing GUI runtime
- **WHEN** the widget test subprocess runs without its required GUI dependency
- **THEN** the collected wrapper test fails with a dependency diagnostic rather than skipping or passing

#### Scenario: Headless models and CLI
- **WHEN** the model and non-GUI CLI tests run without display variables and with GUI toolkit imports forbidden
- **THEN** they pass without loading a GUI toolkit

### Requirement: Deterministic checks preserve writer-visible reports
The deterministic checker SHALL preserve banned-phrase snippets, repeated n-gram
counts and locations, scene selection, report headings, and saved report content
when its calculation is isolated for regression testing.

#### Scenario: Check a synthetic branching project
- **WHEN** the checker runs against synthetic scenes with active and inactive branches, mixed-case banned phrases, and repeated word sequences at a fixed time
- **THEN** stdout and the saved report match the expected report
- **AND** only active branches contribute, and selecting one scene excludes the others

#### Scenario: Check a project without matching text
- **WHEN** scenes are empty or contain neither banned phrases nor qualifying repeated sequences
- **THEN** each report section displays `(none)` and the checker exits successfully

### Requirement: The project check entry point covers the suite
With `tests/` present, `./scripts/check.sh` SHALL run syntax checks, the CLI help smoke test, and the discovered regression suite when uv is available, provisioning the tested PySide6 range for tests through that existing entry point. Test failures SHALL cause a nonzero exit; missing uv SHALL not silently skip the suite. Offscreen success SHALL not be reported as real Wayland acceptance.

#### Scenario: Run all checks
- **WHEN** a maintainer runs `./scripts/check.sh` with uv installed and passing tests
- **THEN** output includes `== syntax`, `== cli smoke`, `== tests`, and the passing test summary with exit 0
- **AND** the test environment includes the tested Qt dependency and executes widget coverage offscreen alongside existing offline coverage

#### Scenario: A regression is detected
- **WHEN** a collected test fails and the maintainer runs `./scripts/check.sh`
- **THEN** the failing test is reported and the script exits nonzero

#### Scenario: uv is missing
- **WHEN** `tests/` exists and the script runs without uv on PATH
- **THEN** the script exits nonzero and explains that uv is required to run the suite

#### Scenario: Existing network guards still apply
- **WHEN** model, CLI, or offscreen widget coverage attempts an unmocked network connection
- **THEN** the existing network guard rejects it in-process or in the subprocess and the test fails
- **AND** no GUI-related network exemption or private project fixture is added

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
