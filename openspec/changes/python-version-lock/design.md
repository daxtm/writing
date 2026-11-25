# Design

## Context

See [proposal.md](proposal.md) for motivation. This is a proposal only.

**Implementation baseline:** `dd9803e` on `feat/guided-workflow`, not the
older `origin/main` from which `ock branch` created this proposal branch.
Build must start with that committed fix present. Do not reintroduce or
reimplement its floor change: its builder already requests 3.13, checks
`>=3.12`, and `tests/test_standalone.py` already contains
`test_build_python_does_not_drop_none_refcount_under_qt_churn`.
That test probes the build venv, not an interactive frozen Wayland session.

The relevant existing boundaries are:

- `longform.py`: thin PEP 723 launcher, currently `requires-python >=3.12`
  on the implementation baseline.
- `scripts/build-standalone.sh`: provisions an independent venv, installs
  the pinned closure, freezes, and writes sidecars.
- `scripts/check.sh`: host `python3` syntax compilation, source smoke,
  standalone build, frozen pytest, then source/Qt pytest. These currently
  choose Python independently.
- `scripts/standalone_sidecars.py`: already records actual implementation
  and patch version.
- `tests/test_check_script.py`: fake-command check-entry-point contracts.
- `tests/test_standalone.py`: production build/reuse fixture, copied-binary
  journeys, sidecar assertions, and the committed Qt churn regression.
  Reuse currently relies primarily on input modification times.

The existing local sidecar and installed interpreter both report ordinary
CPython **3.13.15**. This is a concrete baseline, not a claim that it is the
latest release. A researcher was requested but nesting was unavailable;
selection syntax was checked against installed `uv 0.12.13` help instead:
`uv help python` accepts `implementation@version`, and `uv help run` /
`uv help venv` document explicit `--python` and `UV_PYTHON`.
No future Qt release is assumed.

ADRs 0010–0012 already exist on the implementation baseline; 0013 is the
next number even though this proposal branch's older index lacks those rows.

## Goals / Non-Goals

**Goals:** Make Python selection explicit, fail on drift, and preserve the
already-fixed crash coverage using existing entry points.

**Non-goals:** Universal prevention of someone manually importing the package
under an unsupported interpreter, pinning distributor build revisions,
replacing uv, broad dependency locking, or a new runtime diagnostic command.
The supported source execution contract remains the uv/PEP 723 launcher.

## Decisions

### One authority, one necessary metadata mirror

[ADR-0013](../../../docs/adr/0013-exact-python-runtime-pin.md) chooses a root
`.python-version` containing exactly `cpython@3.13.15` plus a trailing newline.
Reject missing, empty, multi-line, range, minor-only, debug, free-threaded,
and non-CPython requests in the build/check scripts. Keep validation small
and local to those existing shell scripts; do not introduce another runner.

Change PEP 723 `requires-python` to `==3.13.15`, because a checkout-local pin
alone is insufficient to constrain every absolute-path source invocation or
explicit uv override. This is an intentional tightening beyond `dd9803e`'s
floor fix. A regression compares the exact metadata mirror with the authority;
it must fail if only one changes. Preserve the minimum-3.12 safety assertion
as an independent protection against an unsafe future pin.

The alternative, a 3.13 minor pin plus `>=3.12`, fixes the known crash but
does not meet “never drift.” Embedding another hand-maintained runtime
constant would create a third value to synchronize and is unnecessary.

### Fix interpreter selection in the existing scripts

Both scripts resolve the repository root as today, read the pin, and pass
the full CPython request explicitly to uv, rather than trusting host PATH,
`UV_PYTHON`, or an active virtual environment.

Before installing dependencies, the builder runs its provisioned interpreter
to verify CPython, all three release components, a final release, and an
ordinary build (not debug/free-threaded). A mismatch fails with expected and
actual values before pip or PyInstaller runs. Provisioning failure must name
the requested interpreter and must not retry a looser request.

Checks require uv before syntax compilation. Use explicit pinned, isolated uv
runs for preflight, compilation, and the two pytest processes; use the same
explicit request for the existing script smoke. Verify the interpreter during
preflight and print `== python: CPython 3.13.15` only after successful
verification. Keep existing phase markers and ordering after that preflight.
Do not invoke bare `python3`, skip the source smoke, or use the host interpreter
as a fallback. Existing `sys.executable` subprocesses inherit the selected
runner; test this rather than rewriting their callers.

Update fake-command contracts to copy the pin into synthetic check repos,
model the new preflight, and check interpreter arguments for every phase.
Retain their failure-propagation and mandatory-coverage assertions. Use
controlled fake uv/interpreter responses to exercise mismatches without
requiring multiple real Python installations or live provisioning.

### Extend evidence and cache validation, not the packager

Add `interpreter.requested` to the existing build sidecar, containing the full
pin request. Keep `implementation` and `version` derived from the actual build
interpreter rather than copying the expected value into them.

Extend the existing `built` fixture's inputs with `.python-version`. Before
reuse, compare the requested pin, sidecar's actual CPython release, and actual
build-venv interpreter against the current pin, in addition to freshness.
Missing/unreadable metadata or disagreement invalidates reuse and triggers
the production builder; failure never falls back to the old executable.
Test this comparison with synthetic cache metadata, including a newer-mtime
artifact from another pin, to avoid repeatedly rebuilding large binaries.
The real frozen suite still builds and tests the production artifact once.

The existing sidecar test must assert full equality, not just `>=3.12`;
also retain the floor and Qt churn safety checks from `dd9803e`. No separate
frozen debug/probe command or alternate PyInstaller test artifact is needed.
Copied-executable tests continue to prove operation with no checkout, uv,
Python, sidecars, or adjacent pin file.

### Updates are deliberate and documented

Build updates `.python-version`, its exact PEP 723 mirror, and existing
runtime guidance in `AGENTS.md`, `openspec/config.yaml`, `docs/standalone.md`,
and CLI source-run guidance together. Text should distinguish the maintained
exact interpreter policy from the underlying crash-related 3.12 floor.
Do not present a minor-only request as reproducible provisioning.
Run complete checks for every pin update; do not auto-upgrade the pin.

## Risks / Trade-offs

- [Exact Python unavailable] → Fail with the requested version and recovery
  guidance; provisioning may use network, but application/test traffic remains
  guarded. Do not silently accept a newer patch.
- [Mirrored metadata drifts] → Compare it to `.python-version` in mandatory
  regression coverage; one reviewed update changes both.
- [Native-runtime regression despite equal versions] → Keep mandatory Qt
  churn, actual copied-binary tests, and existing separate owner Wayland
  acceptance. Automated/offscreen success is not desktop acceptance.
- [Old sidecars lack the pin] → Invalidate once and rebuild; do not infer an
  expected patch from artifact timestamps.
- [Dependency or distributor drift] → Explicitly outside this Python-version
  guarantee; existing dependency pins and compatibility metadata remain.

## Migration Plan

Build only after the `dd9803e` baseline is available. Add the pin and tighten
metadata, then adapt existing build/check/test boundaries. The first build
recreates the standalone venv; old executables remain ordinary immutable
copies and are not silently upgraded. No writer project files change.

For rollback, revert this pin-enforcement change while retaining `dd9803e`'s
Python safety floor and Qt regression. Any future reviewed pin must remain
at least Python 3.12 while the current Qt binding closure is in use.

## Review / Acceptance

No implementation or runtime checks are claimed by this proposal. After
build, run `./scripts/check.sh`: expect the exact Python line, all existing
phase markers, the existing churn regression, and passing mandatory suites.
Inspect the sidecar's requested/actual values and run the copied executable's
`--help`. The owner's pending real Wayland acceptance remains pending.
There are no unresolved design questions.
