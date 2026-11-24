# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

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
