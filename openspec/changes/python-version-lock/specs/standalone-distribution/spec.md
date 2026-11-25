# Spec Delta

## ADDED Requirements

### Requirement: Freeze the reviewed CPython minor
The standalone build SHALL explicitly select and verify the repository's CPython minor, initially `cpython@3.13`, before installing dependencies or freezing. It SHALL fail on another minor or implementation rather than use a fallback. The independent CPython >=3.12 crash-floor assertion and Qt/None-refcount regression from `dd9803e` SHALL remain unchanged.

#### Scenario: Build on a host with a different default Python
- **WHEN** the documented standalone build runs with another Python first on PATH or a conflicting `UV_PYTHON` value
- **THEN** it either provisions CPython 3.13.x and builds successfully or exits nonzero without freezing on another minor or implementation
- **AND** a successful build's `dist/longform-build.json` records the requested minor `cpython@3.13`, actual implementation, and actual full interpreter version

#### Scenario: Provisioning returns the wrong interpreter
- **WHEN** provisioning fails or returns another implementation, CPython 3.12, or CPython 3.14+
- **THEN** the build exits nonzero before dependency installation and freezing, identifying the expected CPython minor and the provisioning failure or actual interpreter

#### Scenario: Preserve the committed crash fix
- **WHEN** mandatory standalone tests run after the minor policy is applied
- **THEN** the existing build-interpreter Qt churn test completes without an abort or a decreasing None reference count
- **AND** the existing copied-executable and GUI-packaging tests still pass without network calls

### Requirement: Resolve patch updates without changing the minor policy
Build provisioning SHALL resolve the latest available patch of the requested CPython minor automatically. A patch update within 3.13 SHALL require no pin or launcher-metadata edit and SHALL NOT be rejected for differing from a previously recorded patch. Only a minor-policy change SHALL require a reviewed pin/mirror update.

#### Scenario: A newer 3.13 patch becomes available
- **WHEN** the build entry point provisions Python after its resolver offers a newer 3.13 patch than the installed one
- **THEN** it selects that newer patch without changing `.python-version` or the launcher's metadata
- **AND** it records the actual full version without requiring equality to a fixed patch number

### Requirement: Do not reuse standalone artifacts from another CPython minor
Standalone tests SHALL treat the minor pin as a build input and reject cached artifacts or build environments whose recorded or actual implementation/minor does not match it. Missing or unreadable interpreter metadata SHALL invalidate reuse. Patch differences within the pinned minor alone SHALL NOT invalidate reuse; existing other freshness checks SHALL remain.

#### Scenario: Pin changes after an executable was built
- **WHEN** standalone tests encounter an executable built under a different requested or actual CPython minor, even if its modification time is newer than the current source files
- **THEN** they rebuild through the production build script before running copied-executable tests
- **AND** a failed rebuild fails the tests rather than accepting the old artifact

#### Scenario: Cached build evidence is missing or mismatched
- **WHEN** standalone tests encounter missing or unreadable build metadata, a mismatched requested minor, or another recorded or build-environment implementation/minor
- **THEN** they invalidate the cache and require a successful production rebuild
- **AND** copying only a valid executable elsewhere still requires no pin file, sidecar, Python installation, or uv at runtime

#### Scenario: Cached artifact and build environment use different allowed patches
- **WHEN** otherwise fresh cached artifact metadata records a different 3.13 patch from the build environment and both are CPython 3.13.x under the requested minor
- **THEN** the fixture accepts that cache without requiring patch equality or rebuilding solely for the patch difference
