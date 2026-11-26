# Design

## Context

See [proposal.md](proposal.md) for motivation. The owner has authorized build
after this minor-policy revision; this commit contains planning artifacts only.

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

The currently available baseline patch is CPython **3.13.15**; it is an
observation, not a version to require in a file or assertion. A researcher
was requested but nesting was unavailable. Installed `uv 0.12.13` help
documents `implementation@version`, explicit `--python`, `--managed-python`,
and `uv python install --upgrade` for latest-patch provisioning of a minor.
It also says available downloads are bundled with uv, so “latest available”
means the latest supported patch offered by the provisioning uv resolver,
not a promise to discover future releases without updating uv.
No future Qt release is assumed.

ADRs 0010–0012 already exist on the implementation baseline; 0013 is the
next number even though this proposal branch's older index lacks those rows.

## Goals / Non-Goals

**Goals:** Make minor/implementation selection explicit, accept automatic
3.13 patch updates, and preserve the already-fixed crash coverage using
existing entry points.

**Non-goals:** Universal prevention of someone manually importing the package
under an unsupported interpreter, freezing a patch or distributor build revision,
replacing uv, broad dependency locking, or a new runtime diagnostic command.
The supported source execution contract remains the uv/PEP 723 launcher.

## Decisions

### One authority, one necessary metadata mirror

[ADR-0013](../../../docs/adr/0013-cpython-minor-runtime-pin.md) chooses a root
`.python-version` containing `cpython@3.13` plus a trailing newline.
Reject missing, empty, multi-line, range, patch-specific, variant-suffixed,
and non-CPython requests in the build/check scripts. Keep validation small
and local to those existing shell scripts; do not introduce another runner.

Change PEP 723 `requires-python` to `>=3.13,<3.14`, because a checkout-local pin
alone is insufficient to constrain every absolute-path source invocation or
explicit uv override. This is an intentional tightening beyond `dd9803e`'s
floor fix, but accepts every allowed 3.13 patch. A regression derives the
minor's inclusive lower/exclusive next-minor bounds and compares the metadata
mirror with them; it must fail if only one changes. Test both 3.12 and 3.14
rejection, and acceptance of two different synthetic 3.13 patches. Leave the
independent CPython >=3.12 crash-floor assertion and the existing Qt churn
regression from `dd9803e` unchanged.

The owner rejected the exact-patch alternative: patch updates must not need
a reviewed two-file edit. An open-ended `>=3.12` still permits another minor.
No additional hand-maintained interpreter constant or patch value is needed.

### Fix interpreter selection in the existing scripts

Both scripts resolve the repository root as today, read the pin, and pass
the CPython minor request explicitly to uv, rather than trusting host PATH,
`UV_PYTHON`, or an active virtual environment. At provisioning time run
`uv python install --upgrade "$request"` with the validated `cpython@3.13`
request. A minor request alone can reuse an installed old patch: explicit
upgrade is necessary for the automatic latest-available-patch policy.
Use managed Python selection for subsequent venv/run commands so host Python
cannot outrank the upgraded interpreter. Preserve `uv venv --clear` for
the build and isolated uv runs for checks, avoiding stale user environments.
Do not persist the resolved patch as another pin.

Before installing dependencies, add a check that the provisioned builder is
CPython and its `sys.version_info[:2]` matches the requested major/minor.
A mismatch fails with expected and actual values before pip or PyInstaller
runs. Provisioning failure names the requested minor and does not retry a
looser request. Leave the existing independent >=3.12 assertion intact.

Checks require uv before syntax compilation. Use explicit pinned, isolated uv
runs for preflight, compilation, and the two pytest processes; use the same
explicit request for the existing script smoke. Verify the interpreter during
preflight and print `== python: CPython 3.13.<patch>` with the actual full
version only after successful implementation/minor verification. The literal
`<patch>` is a placeholder, never an expected fixed value. Keep existing
phase markers and ordering after that preflight/provisioning.
Do not invoke bare `python3`, skip the source smoke, or use the host interpreter
as a fallback. Existing `sys.executable` subprocesses inherit the selected
runner; test this rather than rewriting their callers.

Bare source uv execution retains its normal resolution/cache behavior within
the allowed minor; its metadata never rejects a newer 3.13 patch. Latest-patch
refresh happens at build/check provisioning, not in application startup.
The application and copied executable do not install Python or self-update.

Update fake-command contracts to copy the pin into synthetic check repos,
model latest-patch provisioning/preflight, and check interpreter arguments
for every phase. Simulate an installed older patch and an offered newer patch
to prove automatic refresh without network or policy edits.
Retain their failure-propagation and mandatory-coverage assertions. Use
controlled fake uv/interpreter responses to exercise mismatches without
requiring multiple real Python installations or live provisioning.

### Extend evidence and cache validation, not the packager

Add `interpreter.requested` to the existing build sidecar, containing the full
minor request `cpython@3.13`. Keep `implementation` and full `version` derived
from the actual build interpreter, not copied from the request.

Extend the existing `built` fixture's inputs with `.python-version`. Before
reuse, compare the requested minor, sidecar's actual implementation/minor,
and actual build-venv implementation/minor against the pin, in addition to
freshness. Missing/unreadable metadata or implementation/minor disagreement
invalidates reuse and triggers
the production builder; failure never falls back to the old executable.
Test this comparison with synthetic cache metadata, including a newer-mtime
artifact from another minor, to avoid repeatedly rebuilding large binaries.
Explicitly test acceptance when the artifact and build venv have different
patches within 3.13. A patch-only difference must not trigger a rebuild:
ordinary input freshness and explicit build/check invocations still can.
The real frozen suite still builds and tests the production artifact once.

The sidecar test adds implementation/minor and requested-minor assertions
alongside the unchanged >=3.12 floor and Qt churn checks from `dd9803e`.
It checks that the full version is recorded but never asserts patch equality
to a constant or to another valid same-minor environment. No separate
frozen debug/probe command or alternate PyInstaller test artifact is needed.
Copied-executable tests continue to prove operation with no checkout, uv,
Python, sidecars, or adjacent pin file.

### Review minor changes, not patch updates

Implementation adds `.python-version`, its bounded-minor PEP 723 mirror, and existing
runtime guidance in `AGENTS.md`, `openspec/config.yaml`, `docs/standalone.md`,
and CLI source-run guidance together. Text should distinguish the maintained
3.13 minor policy from the underlying crash-related 3.12 floor. Provisioning
takes the latest available patch without policy edits. Only a minor bump
changes the authority and bounded mirror in one reviewed change.
Run complete checks after upgrades; neither patch-level nor bit-identical
rebuild reproducibility is promised.

## Risks / Trade-offs

- [Requested CPython minor unavailable] → Fail with the requested minor and recovery
  guidance; provisioning may use network, but application/test traffic remains
  guarded. Do not silently accept another minor or implementation.
- [Resolver does not yet know a new patch] → Keep uv current; the policy uses
  its latest available supported patch, with no patch-specific file edits.
- [Mirrored metadata drifts] → Compare it to `.python-version` in mandatory
  regression coverage; only a reviewed minor bump changes both.
- [Automatic patch introduces a regression] → Keep mandatory Qt
  churn, actual copied-binary tests, and existing separate owner Wayland
  acceptance. Automated/offscreen success is not desktop acceptance.
- [Old sidecars lack the pin] → Invalidate once and rebuild; do not infer an
  implementation/minor from artifact timestamps.
- [Valid same-minor cache retains an older patch] → Allowed by design;
  `./scripts/check.sh` still invokes the production build, while direct frozen
  tests can reuse a valid artifact. Copied executables remain immutable.
- [Dependency or distributor drift] → Explicitly outside this Python-version
  guarantee; existing dependency pins and compatibility metadata remain.

## Migration Plan

Build is owner-authorized after this revision, starting with the `dd9803e`
baseline available. Add the minor pin and bound
metadata, then adapt existing build/check/test boundaries. The first build
recreates the standalone venv; old executables remain ordinary immutable
copies and are not silently upgraded. No writer project files change.

For rollback, revert this minor-enforcement change while retaining `dd9803e`'s
Python safety floor and Qt regression unchanged. Do not turn rollback into
an exact-patch pin. Future reviewed minor changes retain the crash-floor guard.

## Review / Acceptance

No implementation or runtime checks are claimed by this proposal. After
build, run `./scripts/check.sh`: expect the actual CPython 3.13.x line, all existing
phase markers, the existing churn regression, and passing mandatory suites.
Inspect the sidecar's requested/actual values and run the copied executable's
`--help`. The owner's pending real Wayland acceptance remains pending.
There are no unresolved design questions.
