## MODIFIED Requirements

### Requirement: The suite is discoverable from the repository root
The command `uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' pytest -q tests` SHALL discover and run the regression suite from the repository root without installing the CLI as a package. Model and CLI tests SHALL require neither a display nor GUI imports; widget cases SHALL execute in an isolated subprocess using `QT_QPA_PLATFORM=offscreen`.

#### Scenario: Run the documented test command
- **WHEN** a maintainer runs the documented command in a checkout with Python 3.11+ and uv available
- **THEN** tests are collected, the passing summary reports a nonzero number of passed tests, and the command exits 0
- **AND** widget cases actually execute offscreen without requiring a Wayland/X11 session

#### Scenario: Missing GUI runtime
- **WHEN** the widget test subprocess runs without its required GUI dependency
- **THEN** the collected wrapper test fails with a dependency diagnostic rather than skipping or passing

#### Scenario: Headless models and CLI
- **WHEN** the model and non-GUI CLI tests run without display variables and with GUI toolkit imports forbidden
- **THEN** they pass without loading a GUI toolkit

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
