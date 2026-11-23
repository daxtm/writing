# standalone-distribution Specification

## Purpose

Let writers run the existing writing commands from one native executable without installing Python, uv, dependencies, or the source checkout.

## Requirements

### Requirement: Build a self-contained native executable
On a supported Linux x86_64 glibc build host, `./scripts/build-standalone.sh`
SHALL produce the executable `dist/longform`, including its interpreter,
application modules, runtime dependencies, and default TLS trust data.
Building MAY provision dependencies; running SHALL NOT install anything.

#### Scenario: Build from a clean checkout
- **WHEN** a maintainer runs the build command with documented build prerequisites installed
- **THEN** it exits 0 and produces an executable regular file at `dist/longform`
- **AND** neither the source launcher nor private project data is modified or included as a project fixture

#### Scenario: Run only the copied executable
- **WHEN** a writer copies only `dist/longform` to an unrelated directory on the documented compatible Linux runtime and runs `./longform --help` without Python, uv, or the checkout available
- **THEN** it exits 0 and lists the existing CLI commands
- **AND** it neither downloads dependencies nor requires an adjacent package directory

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
notices. Documentation SHALL distinguish bundled Python dependencies from
required host libraries and executable temporary storage; it SHALL NOT claim
universal Linux, GUI, or cross-platform support from a native CLI smoke test.

#### Scenario: Inspect the delivered compatibility information
- **WHEN** a maintainer builds and reads `dist/longform-build.json`, `dist/THIRD-PARTY-NOTICES.txt`, and `docs/standalone.md`
- **THEN** they identify the source revision/dirty state, architecture, build OS/glibc, Python and resolved dependency versions, required host-library boundary, third-party license texts, and build/run commands
- **AND** they explain the executable temporary-directory requirement and the `TMPDIR` workaround for a `noexec` default

### Requirement: Enforce frozen executable coverage in project checks
`scripts/check.sh` SHALL build and test the executable on supported Linux
x86_64 glibc hosts, retain the existing source regression checks, and fail on
build or frozen-test failures. Frozen tests SHALL use synthetic data, no real
credentials, and an effective process-level network guard rather than relying
on source-only monkeypatches.

#### Scenario: Run project checks
- **WHEN** a maintainer runs `./scripts/check.sh` on a supported host with documented prerequisites
- **THEN** output includes `== standalone` and passing copied-binary tests in addition to the existing syntax, CLI smoke, and regression results
- **AND** missing build prerequisites, missing output, or a failing frozen test makes checks exit nonzero rather than skip coverage

#### Scenario: Reject networking inside a frozen test
- **WHEN** the frozen-process guard is challenged by an attempted external socket connection or hostname lookup
- **THEN** it rejects the attempt without contacting external services
- **AND** removing Python/uv from PATH does not disable this guard
