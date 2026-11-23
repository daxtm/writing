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
The command `uv run --with pytest --with httpx pytest -q tests` SHALL discover and
run the regression suite from the repository root without installing the CLI as
a package.

#### Scenario: Run the documented test command
- **WHEN** a maintainer runs the documented command in a checkout with Python 3.11+ and uv available
- **THEN** tests are collected, the passing summary reports a nonzero number of passed tests, and the command exits 0

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
With `tests/` present, `./scripts/check.sh` SHALL run syntax checks, the CLI help
smoke test, and the discovered regression suite when uv is available. Test
failures SHALL cause a nonzero exit; missing uv SHALL not silently skip the suite.

#### Scenario: Run all checks
- **WHEN** a maintainer runs `./scripts/check.sh` with uv installed and passing tests
- **THEN** output includes `== syntax`, `== cli smoke`, `== tests`, and the passing test summary with exit 0

#### Scenario: A regression is detected
- **WHEN** a collected test fails and the maintainer runs `./scripts/check.sh`
- **THEN** the failing test is reported and the script exits nonzero

#### Scenario: uv is missing
- **WHEN** `tests/` exists and the script runs without uv on PATH
- **THEN** the script exits nonzero and explains that uv is required to run the suite
