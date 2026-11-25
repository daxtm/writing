# Spec Delta

## ADDED Requirements

### Requirement: Freeze the reviewed exact Python interpreter
The standalone build SHALL use the repository's exact ordinary CPython pin, initially 3.13.15, and SHALL verify implementation and full release version before installing build dependencies or freezing. It SHALL fail rather than substitute another interpreter. Existing Python 3.12 minimum and Qt/None-reference regression coverage SHALL remain enforced.

#### Scenario: Build on a host with a different default Python
- **WHEN** the documented standalone build runs with another Python first on PATH or a conflicting `UV_PYTHON` value
- **THEN** it either provisions the pinned CPython and builds successfully or exits nonzero without freezing on a different interpreter
- **AND** a successful build's `dist/longform-build.json` records the pinned implementation and full patch version

#### Scenario: Provisioning returns the wrong interpreter
- **WHEN** provisioning fails or returns an interpreter whose implementation, release version, or ordinary-build variant differs from the pin
- **THEN** the build exits nonzero before dependency installation and freezing, identifying the expected interpreter and the provisioning failure or actual interpreter

#### Scenario: Preserve the committed crash fix
- **WHEN** mandatory standalone tests run after the exact pin is applied
- **THEN** the existing build-interpreter Qt churn test completes without an abort or a decreasing None reference count
- **AND** the existing copied-executable and GUI-packaging tests still pass without network calls

### Requirement: Do not reuse standalone artifacts from another interpreter
Standalone tests SHALL consider the Python pin a build input and SHALL NOT accept a cached artifact or build environment whose recorded or actual interpreter differs from it. Missing interpreter metadata SHALL invalidate reuse. Successful builds SHALL record both the requested pin and actual interpreter for comparison.

#### Scenario: Pin changes after an executable was built
- **WHEN** standalone tests encounter an executable built under a different pin, even if its modification time is newer than the current source files
- **THEN** they rebuild through the production build script before running copied-executable tests
- **AND** a failed rebuild fails the tests rather than accepting the old artifact

#### Scenario: Cached build evidence is missing or mismatched
- **WHEN** standalone tests encounter missing or unreadable build metadata, a mismatched recorded pin or actual version, or a build environment with the wrong interpreter
- **THEN** they invalidate the cache and require a successful production rebuild
- **AND** copying only a valid executable elsewhere still requires no pin file, sidecar, Python installation, or uv at runtime
