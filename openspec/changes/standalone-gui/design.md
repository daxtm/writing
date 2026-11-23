# Design

## Context

See [proposal.md](proposal.md) for motivation. Main's standalone builder
already provisions Python 3.11, freezes `longform.py` with PyInstaller
`--onefile --console`, collects certifi data, writes sidecars, and tests a
copied artifact with Python/uv absent from PATH. Its pinned build closure
contains no PySide6. `tests/test_standalone.py` already inspects the archive
and guards the frozen process and children using a challenged native
`LD_PRELOAD` guard; its `AF_UNIX` allowance must remain intact.

The source GUI is a prerequisite, not new work in this packaging change.
The inspected `feat/gui-wayland-shell` revision is
`3d26b7a6d9c0b4cac7027e15e5347544001172bd`. It contains the Qt workspace,
planning/draft/review operations, one worker, `gui DIR`, and offscreen
widget cases. Implement on a baseline containing that work (or its
integrated successor) with its own checks passing; stop and report a missing
prerequisite rather than rebuilding the GUI here. This proposal does not
merge, ship, or assert that main already contains those changes.

That GUI declares `pyside6>=6.12.0,<6.13`, imports Qt lazily, refuses any
explicit platform other than `wayland`, prints startup advice before
constructing `QApplication`, and reports the selected platform and runtime
versions. Its advice currently assumes `uv run --script longform.py`.

## Goals / Non-Goals

- Preserve the source launcher's GUI and CLI behavior while fixing its frozen
  distribution; same executable, no extra user-managed runtime directory.
- Keep console mode, headless CLI use, source Qt offscreen tests, and existing
  editor-environment restoration.
- Do not add a hidden GUI test mode, alternative GUI entry point, compositor
  dependency to automated checks, or runtime dependency installer.
- No new workflow operations, concurrent-writer support, or release automation.

## Decisions

### 1. Extend the existing single-artifact build

[ADR-0009](../../../docs/adr/0009-single-cli-gui-executable.md) selects the
unified one-file executable over a separate GUI directory distribution.
ADR-0006/0007 still govern presentation and operations; ADR-0008 still
governs the native/extraction boundary.

Update `scripts/standalone-requirements.txt` with an exact resolved
PySide6/Shiboken closure within the source GUI's declared range. Resolve for
the existing Python 3.11 Linux target and record the tested versions; do not
invent pins, loosen source constraints, or silently upgrade the freezer.
Retain the existing CLI/TLS dependency pins unless resolution requires an
explicitly documented change.

Use the existing PyInstaller PySide6 hooks and their runtime plugin-path
setup first. Inspect the produced archive for `gui`, `gui_window`, the shared
operation/worker modules, QtCore/QtGui/QtWidgets, Shiboken, and the required
Wayland platform/plugin libraries and their dependency closure. Resolve
exact plugin filenames from the pinned wheel and hook output rather than
assuming a Qt-version-independent name. Missing required GUI components
must fail the build/acceptance test, not produce a successful CLI-only build.
If normal analysis misses an actual lazily imported application module or
required plugin, add only the demonstrated hidden import or collection
directive to this builder; do not collect every Qt module or create a
parallel build system.

Reuse existing freshness checks and include any new packaging inputs, so a
previous CLI-only executable cannot satisfy the GUI tests by being reused.
Extend the existing archive assertions; retain exclusions for tests, private
projects, credentials, and the third-party preset.

### 2. Reuse startup policy; vary only recovery instructions

Keep the existing `gui` dispatch, lazy Qt imports, `resolve_platform`, and
pre-`QApplication` diagnostic. Centralize the displayed launch command so
source mode retains its current uv instruction, while frozen mode uses a
shell-quoted absolute `sys.executable` plus `gui DIR`. The same advice must
serve policy rejection, missing-runtime messages, pre-start guidance,
platform mismatch, and caught startup failures. Test executable paths
containing spaces.

Unset platform still selects Wayland. Do not permit `offscreen`, `xcb`, or
fallback lists in the public command to simplify testing. Native Qt can
abort before Python catches a plugin/session error: the acceptance contract
is nonzero exit plus already-flushed recovery advice, not a promised Python
exception or exact native exit code. Missing-session tests use a nonexistent
socket and isolated runtime directory, not the owner's desktop.

### 3. Extend inventory and notices, not compatibility claims

Keep existing sidecar fields and add GUI information: PySide6/Shiboken/Qt
versions, bundled plugin paths, and native dependency inspection for the
collected Qt libraries/plugins. An executable-only `ldd` report is
insufficient. Inspect the build's collected files before one-file assembly
or safely extract the final archive into build-only storage; distinguish
bundled libraries from remaining host dependencies and fail unresolved
required plugin dependencies. Never record secrets or project contents.

Collect the matching Qt library/plugin and Shiboken license/notice materials
from the pinned installed distributions as well as the existing Python
distribution licenses. Verify actual wheel contents, including materials
outside `.dist-info`; fail on missing required texts rather than assuming
the Python package's license covers every native component. Record what is
bundled and its applicable upstream licensing references without claiming
that notices alone authorize redistribution. No release is authorized.

Update `docs/standalone.md` in the implementation with source-free build/copy/
GUI examples, measured artifact size, extraction/storage costs, Wayland and
host-library prerequisites, diagnostics, and acceptance limits. Sidecars
remain informational at runtime; do not require adjacent Qt directories.

### 4. Layer automated and real-desktop evidence

Extend `tests/test_standalone.py`, its production-build fixture, archive
inspection, and `frozen_env`; do not use a replacement test executable.
Copied-binary tests run from unrelated paths with spaces, empty PATH, no
Python import overrides or host Qt plugin paths, synthetic projects, and
the native network guard. Assert:

- `--help` lists `gui`; CLI init/status/export still work without a display.
- Required GUI application modules, Qt libraries/plugins, notices, and
  metadata are present; forbidden private/test material stays absent.
- Invalid platforms are refused before Qt startup; an unavailable socket
  produces standalone recovery advice and no project writes or networking.
- Existing CLI parity, missing-key/argument cases, TLS data, extraction cleanup,
  and external-editor environment tests remain passing.

Retain the integrated source operation/parity suites and all source
offscreen widget cases. These exercise controls with fake providers without
relaxing the production command's platform policy. Neither archive inspection,
Qt startup failure, nor offscreen widgets proves a functioning frozen window.

Require a separate real native-Wayland acceptance of the copied production
binary before marking this change complete. Use a synthetic project without
credentials, no source/runtime packages in its execution environment, and
the native network guard. Open/reopen, read active/inactive branches, save
multiline steering, edit a scene card, save a new manual passage, export
via the destination picker, and close normally. Compare saved files/export
against the source CLI. Confirm one window, platform `wayland`, keyboard,
mouse, clipboard, file picker, resize, and available light/dark and
100%/200%/fractional scaling. Exercise only available monitor configurations;
record unavailable cases explicitly.

Record commands, checksum/revision, OS/glibc, compositor, runtime versions,
scaling/theme, and outcomes in this change's `evidence.md`. If a real desktop
is unavailable, record PENDING and leave desktop acceptance unchecked; do
not substitute offscreen success or claim workspace completion.

### 5. Default the bare invocation to the GUI

A launch with no arguments SHALL dispatch to the same GUI path as `gui [DIR]`
with the current working directory. This covers file-manager double-click and
accidental bare launches; it is not a separate window or test-only mode. The
`gui` subcommand accepts an optional `DIR`, and every explicit command keeps
its existing required arguments. `--help` stays a normal argparse help exit.
A non-project current directory is handled by the existing workspace
Create/Open controls with no writes until the owner confirms. Both source and
frozen modes use the same dispatch, and frozen recovery advice still names the
copied executable.

## Risks / Trade-offs

- Qt/plugin dependency differences → inspect the pinned artifact and verify it
  on the actual desktop; no older-distro or universal Linux promise.
- Larger CLI artifact and slower extraction → record size/storage costs;
  accept them under ADR-0009 rather than split delivery.
- Frozen advice accidentally falls back to uv → test every existing startup
  message site and an executable path containing spaces.
- Source GUI remains unintegrated or fails its own checks → stop at that
  prerequisite; do not silently reduce this change to packaging a reader.
- Headless checks pass while Wayland is broken → require separate copied-
  binary desktop evidence and keep the task open when unavailable.

## Migration Plan

After the source GUI prerequisite is present, extend the current build and
tests; project files need no migration. Rebuild `dist/longform` and its
matching metadata/notices together. Do not publish or merge as part of this
proposal. A packaging rollback restores the previous CLI-only executable;
it does not rewrite saved writing projects.

## Research Basis

Researcher delegation was attempted but blocked by the session's subagent
depth limit. The following official pinned implementation sources were
read directly instead; they support hook reuse, not a claim that this
particular PySide6/Wayland artifact has already been verified:

- [PyInstaller 6.22.3 QtWidgets hook](https://github.com/pyinstaller/pyinstaller/blob/v6.22.3/PyInstaller/hooks/hook-PySide6.QtWidgets.py): delegates Qt dependency collection.
- [Qt collection utilities](https://github.com/pyinstaller/pyinstaller/blob/v6.22.3/PyInstaller/utils/hooks/qt/__init__.py): binding-specific library/plugin layouts and dependency collection.
- [PySide6 runtime hook](https://github.com/pyinstaller/pyinstaller/blob/v6.22.3/PyInstaller/hooks/rthooks/pyi_rth_pyside6.py): extracted-bundle plugin paths and single-binding setup.

The Qt for Python PyInstaller page includes explicitly dated March 2021 Qt 6
limitations; it is not used as evidence for current one-file support.
Actual pinned wheels, license materials, native dependencies, and a running
frozen window remain implementation verification, not established results.
