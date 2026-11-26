# standalone-distribution Specification

## Purpose

Let writers run the existing writing commands from one native executable without installing Python, uv, dependencies, or the source checkout.

## Requirements

### Requirement: Build a self-contained native executable
On a supported Linux x86_64 glibc build host, `./scripts/build-standalone.sh`
SHALL produce `dist/longform` with its interpreter, existing CLI and GUI,
Python dependencies, required Qt libraries/plugins, and TLS trust data.
Building MAY provision dependencies; running SHALL NOT install anything.
The GUI SHALL require no separately installed Python, uv, PySide6, or Qt
package directory on the documented compatible runtime.

#### Scenario: Build from a clean checkout
- **WHEN** a maintainer runs the build command with documented build prerequisites installed and the existing Qt workspace integrated
- **THEN** it exits 0 and produces an executable regular file at `dist/longform` containing the CLI, GUI, and required Qt runtime
- **AND** neither the source launcher nor private project data is modified or included as a project fixture

#### Scenario: Run only the copied executable
- **WHEN** a writer copies only `dist/longform` to an unrelated directory on the documented compatible Linux runtime and runs `./longform --help` without Python, uv, or the checkout available
- **THEN** it exits 0 and lists the existing CLI commands and `gui [DIR]`
- **AND** it neither downloads dependencies nor requires an adjacent package directory

#### Scenario: Use the CLI without a display
- **WHEN** the copied executable runs `--help`, `init`, `status`, or `export` without display variables or an available Wayland socket
- **THEN** the commands retain their existing output, file behavior, and exit statuses without attempting GUI startup

### Requirement: Preserve the writing CLI contract
The executable SHALL expose the existing command arguments, prompts, exit
statuses, credential lookup, project-file semantics, and output. The source
launcher SHALL remain supported. Only the invoked program name in argparse
usage and temporary absolute paths MAY differ.

#### Scenario: Initialize, inspect, and export away from the checkout
- **WHEN** the copied executable runs `init`, repeated `init`, `status`, `check`, and `export --out` against synthetic temporary projects, including paths containing spaces
- **THEN** output, errors, and saved project/report/manuscript content match the source launcher after normalizing only program name, fixture timestamps, and temporary roots
- **AND** output files resolve relative to the caller or supplied project as before, not the executable or extraction directory

#### Scenario: Missing credentials and invalid arguments
- **WHEN** the executable runs `limits` without credentials or receives invalid command arguments
- **THEN** each invocation matches the source launcher's diagnostic and nonzero exit status without making an API call

#### Scenario: Keep source invocation working
- **WHEN** a maintainer runs `uv run --script longform.py --help` and the existing offline regression suite
- **THEN** the launcher prints the existing command list and the suite passes

### Requirement: Preserve external editor invocation
The executable SHALL honor existing `VISUAL`/`EDITOR` behavior without leaking
its private bundled-library search path into the editor. An editor remains an
optional user-supplied program, not a bundled dependency.

#### Scenario: Edit a passage with a user-supplied editor
- **WHEN** a synthetic draft session in the executable invokes a temporary fake editor through `EDITOR`
- **THEN** the editor receives the expected text file, its edits are saved through the existing draft flow, and it sees the original host library search environment
- **AND** source-launcher editor behavior remains unchanged

### Requirement: Document the actual native compatibility boundary
Build output SHALL include adjacent compatibility metadata and third-party
notices covering the bundled CLI and Qt runtime. Documentation SHALL
distinguish bundled dependencies from required host libraries, compositor,
and executable temporary storage. GUI support claims SHALL identify actual
frozen-binary Wayland evidence, not infer desktop support from CLI or offscreen tests.

#### Scenario: Inspect the delivered compatibility information
- **WHEN** a maintainer builds and reads `dist/longform-build.json`, `dist/THIRD-PARTY-NOTICES.txt`, and `docs/standalone.md`
- **THEN** they identify the source revision/dirty state, architecture, build OS/glibc, Python and resolved dependency versions, required host-library boundary, third-party license texts, and build/run commands
- **AND** they explain the executable temporary-directory requirement and the `TMPDIR` workaround for a `noexec` default
- **AND** they identify PySide6/Shiboken and Qt versions, bundled platform plugins, native GUI dependency information beyond the executable's own library list, and the Wayland runtime prerequisites
- **AND** bundled Qt/Shiboken component notices and matching license texts are present, with absent required texts making the build fail

#### Scenario: Separate desktop evidence from automated checks
- **WHEN** a maintainer reads the standalone GUI acceptance record
- **THEN** it distinguishes automated copied-binary and source offscreen results from real frozen-binary Wayland results, including any pending desktop checks
- **AND** a real desktop result records the binary checksum/source revision, compositor, distribution, Qt platform, runtime versions, scaling, and interaction results rather than claiming universal Linux or cross-platform support

### Requirement: Enforce frozen executable coverage in project checks
`scripts/check.sh` SHALL build and test the executable on supported Linux
x86_64 glibc hosts, retain existing source checks, and fail on build or
frozen-test failures. Frozen tests SHALL cover GUI discovery, bundled GUI
dependencies, and startup diagnostics using synthetic data and the existing
effective process-level network guard, not source-only monkeypatches.

#### Scenario: Run project checks
- **WHEN** a maintainer runs `./scripts/check.sh` on a supported host with documented prerequisites
- **THEN** output includes `== standalone` and passing copied-binary tests in addition to the existing syntax, CLI smoke, and regression results
- **AND** frozen GUI discovery, runtime inventory, and startup-failure cases execute without needing a desktop session
- **AND** missing build prerequisites, missing output, or a failing frozen test makes checks exit nonzero rather than skip coverage
- **AND** existing offscreen Qt widget coverage remains mandatory and is not treated as real Wayland acceptance

#### Scenario: Reject networking inside a frozen test
- **WHEN** the frozen-process guard is challenged by an attempted external socket connection or hostname lookup
- **THEN** it rejects the attempt without contacting external services
- **AND** removing Python/uv from PATH does not disable this guard

### Requirement: Open the existing workspace from the copied executable
The copied executable's `gui DIR` SHALL expose the same existing workspace,
controls, shared writing operations, and saved-file behavior as the source
GUI on a compatible native Wayland desktop. Packaging SHALL NOT reduce it
to a read-only reader or introduce different prompts, credential handling,
or project formats. Closing an idle window normally SHALL exit 0.

#### Scenario: Open and persist steering without Python tooling
- **WHEN** a writer starts `QT_QPA_PLATFORM=wayland /absolute/path/longform gui "project with spaces"` using only the copied executable on the documented desktop runtime, selects a saved scene, saves multiline steering, closes, and reopens
- **THEN** one native Wayland workspace opens per invocation with the same saved manuscript/branches and controls as the source workspace
- **AND** steering survives reopening, a normal idle close exits 0, and no dependency installation or unsolicited API request occurs

#### Scenario: Retain planning, drafting, and export controls
- **WHEN** a writer uses the copied executable to open a synthetic project, edit/save a scene card, save a new manual passage through the existing draft controls, and export to a chosen destination
- **THEN** these actions work through the existing workspace without terminal prompts or external editors
- **AND** the source CLI reads the same saved card and active passage and produces the same manuscript at an equivalent export destination

### Requirement: Launch the bundled GUI by default
Invoking the copied executable with no arguments SHALL take the same GUI
default as the source launcher: attempt the native workspace for the current
working directory without requiring an explicit `gui` command, Python, uv, or
the checkout. The existing native-Wayland policy and recovery guidance SHALL
apply unchanged.

#### Scenario: Double-click or bare executable
- **WHEN** the copied executable runs with no arguments from a file manager or shell and no Python, uv, or checkout is available
- **THEN** it attempts the native Wayland workspace for the current directory instead of reporting a missing command
- **AND** without a usable Wayland session it exits nonzero with the same frozen recovery advice as `gui`
- **AND** a non-project directory is handled by the workspace Create/Open controls without writing project files

### Requirement: Preserve native Wayland policy with standalone recovery advice
The frozen GUI SHALL preserve native-Wayland-only startup and refuse explicit
alternative platforms or fallback lists. Unavailable Wayland/plugin/system
support SHALL produce a nonzero exit and actionable stderr guidance before
any possible native Qt startup abort. Frozen guidance SHALL reference the
copied executable and desktop prerequisites, not require uv or source.

#### Scenario: Refuse unsupported platforms
- **WHEN** the copied executable runs `gui DIR` with `QT_QPA_PLATFORM` set to `xcb`, `offscreen`, or a fallback list
- **THEN** it exits nonzero with native Wayland guidance without opening a fallback window, writing project files, or making an API request

#### Scenario: Missing Wayland session
- **WHEN** the copied executable runs `gui DIR` with platform unset or `wayland`, no usable Wayland socket, and no Python/uv/source available
- **THEN** it exits nonzero with guidance to check the Wayland session/socket and Qt host libraries and retry the copied executable
- **AND** it does not suggest installing dependencies with uv, open an XWayland window, modify the project, or contact a provider

### Requirement: Bundle complete new-project defaults inside the executable
The copied executable SHALL include the reviewed application-owned project
defaults and writer preset and create the same complete setup as source init.
Runtime, build and tests SHALL NOT access the owner's original source files.
No adjacent defaults directory, runtime download or manual preset copy SHALL
be required.

#### Scenario: Initialize away from the checkout
- **WHEN** only the executable is copied to an unrelated directory and runs `init` against a fresh path containing spaces with no Python/uv on PATH, no display, blocked network and the owner's source paths unavailable
- **THEN** it exits 0 and creates the same six files and seven directories as source init, including matching configuration and usable preset bytes
- **AND** output matches source after existing program-name/root normalization and neither cwd nor executable-adjacent files supply the defaults

#### Scenario: Repeat and override in the copied executable
- **WHEN** copied-executable init is repeated or supplies an explicit synthetic `--preset FILE`
- **THEN** source/frozen output, warnings, errors and create-missing-only behavior agree, including exact override bytes for a missing destination and preservation of an existing preset

#### Scenario: Build using only reviewed repository assets
- **WHEN** the existing standalone build runs with the owner's original project and preset files inaccessible
- **THEN** it packages only the reviewed application-owned defaults and completes without reading those originals
- **AND** `docs/standalone.md` and distributed third-party notices identify the bundled preset's recorded provenance and applicable source notices without exposing private data

#### Scenario: Missing or corrupt bundled defaults
- **WHEN** an installation or test build lacks a required defaults asset or contains an invalid bundled preset
- **THEN** init fails with an actionable diagnostic instead of reporting complete setup, reading the owner's paths or downloading a replacement
- **AND** it preserves existing project files and reports any completed writes

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
