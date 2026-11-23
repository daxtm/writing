# Evidence — standalone-gui

Host: Linux x86_64, glibc 2.44 (`ldd (GNU libc) 2.44`), uv-managed CPython
3.11.15, build PyInstaller 6.22.3 with pyinstaller-hooks-contrib 2026.10,
PySide6 6.12.0 (`pyside6-essentials`), Shiboken6 6.12.0, Qt 6.12.0.
No Wayland session is available on this host (`XDG_SESSION_TYPE=tty`, no
`WAYLAND_DISPLAY`), so task 1.6 remains PENDING; automated checks use offscreen
widget cases and synthetic missing-socket startup failures only.

## Commands and results

### Task 1.1 — owner-visible frozen discovery/archive tests (commit `e0e13df` baseline, red by design)

- Added `gui` to the copied-binary `--help` command list, GUI application
  modules to the archive assertions, native Qt/Shiboken bindings and the Wayland
  platform/plugin closure to the archive assertions, and new-input freshness
  checks.
- Red run against the pre-change CLI-only artifact, `pytest -q
  tests/test_standalone.py -k archive_contains`: **2 failed, 1 passed** —
  `PySide6`/`shiboken6` absent from the PYZ archive; `libQt6Core.so` absent from
  the CArchive. The `--help` test passed only because it did not yet list `gui`.
- Green run after the Qt-capable build: archive tests pass (see tasks 1.2 and
  1.4 below).

### Task 1.2 — pinned Qt closure and production build

- `scripts/standalone-requirements.txt` adds `pyside6-essentials==6.12.0` and
  `shiboken6==6.12.0` (inside the unchanged source range
  `pyside6>=6.12.0,<6.13`), avoiding Addons/WebEngine/PDF.
- `./scripts/build-standalone.sh` → `dist/longform`, one-file console,
  GUI-capable. Archive entries: 291; unpacked content 212.3 MiB. The PYZ
  contains the GUI dispatch/window, shared operations/worker/reader/steering
  modules, `PySide6` and `shiboken6`; `PySide6/QtCore.abi3.so`,
  `QtGui.abi3.so`, `QtWidgets.abi3.so` and `shiboken6/Shiboken.abi3.so` are
  native CArchive entries. Qt libraries include `libQt6Core/Gui/Widgets`,
  `libQt6WaylandClient`, `libQt6WlShellIntegration`, `libpyside6` and
  `libshiboken6`; plugin inventory has 50 entries including
  `PySide6/Qt/plugins/platforms/libqwayland.so`, five Wayland shell plugins
  (`libxdg-shell.so` included), decoration and graphics-integration clients.
- Private/test materials remain absent (`myfic`, `tests`, `.env`, fixture and
  preset names) and the existing network guard, CLI parity, editor-environment,
  TLS and extraction-cleanup tests remain green.
- Glibc boundary: the pinned PySide6 wheel is `manylinux_2_34_x86_64`, so the
  standalone GUI requires glibc 2.34+.

### Task 1.3 — invocation-aware recovery guidance

- `longform_core.gui.launch_advice()` centralizes the command used by policy
  rejection, missing-runtime, pre-start guidance, platform-mismatch and caught
  startup-failure messages. Source mode keeps
  `QT_QPA_PLATFORM=wayland uv run --script longform.py gui DIR`; frozen mode
  uses `QT_QPA_PLATFORM=wayland <shell-quoted absolute sys.executable> gui DIR`.
- Red/green: the frozen xcb run originally told the user to run uv; after the
  change, `QT_QPA_PLATFORM=xcb ./dist/longform gui /tmp/x` printed
  `gui requires native Wayland; ... Run: QT_QPA_PLATFORM=wayland
  /home/.../dist/longform gui DIR`, exit 1. A missing Wayland socket with
  unset/explicit `wayland` flushed
  `longform gui: native Wayland is required. ... retry:
  QT_QPA_PLATFORM=wayland /home/.../dist/longform gui DIR`, then Qt aborted
  natively with exit 134 (accepted nonzero-exit contract; recovery advice was
  already emitted).
- Verified source and copied-binary regressions for `xcb`, `offscreen`,
  `wayland,xcb`, `wayland,offscreen`, unset/explicit `wayland`, missing socket,
  and paths containing spaces; refused GUI starts make no project writes and no
  network calls, and frozen advice never mentions uv or the source launcher.

### Task 1.4 — metadata, notices, native inspection, docs

- `scripts/standalone_sidecars.py` (build-only) now validates the actual
  archive and writes both sidecars:
  - `dist/longform-build.json` retains all existing fields and adds
    `gui.pyside6`, `gui.shiboken6`, `gui.qt`, `gui.bindings_distribution`,
    `gui.license`, `gui.inventory` (bindings, libraries, all plugins, Wayland
    platform/shell/decoration/graphics lists) and
    `gui.native_dependency_inspection` (per-file `ldd`, bundled versus host
    sets). 20 required native files are inspected; no unresolved dependency is
    accepted.
  - `dist/THIRD-PARTY-NOTICES.txt` adds the PySide6/Shiboken/Qt section with
    the bundled plugin inventory and canonical SPDX LGPLv3/GPLv2/GPLv3 texts
    vendored under `scripts/standalone-licenses/` (those wheels ship no license
    files; provenance and SHA-256 are recorded in the README there).
- Missing-material failures are proven in `tests/test_standalone_sidecars.py`:
  missing Wayland/xdg-shell/decoration/graphics plugins, missing Qt library,
  unresolved `ldd` dependency and missing vendored license text each raise
  `SidecarError`; the production build exits nonzero instead of writing
  incomplete notices. The earlier production failure
  `build-standalone: error: no license text found for PySide6_Essentials
  6.12.0` is the red case this fixes.
- `docs/standalone.md` documents the GUI build/copy/run path, pinned Qt
  versions, glibc 2.34 requirement, measured ~85 MB artifact / ~212 MiB
  extraction, bundled-versus-host Wayland/GL boundary, diagnostics, sidecar
  contents, licensing limits and the separate desktop acceptance.

### Task 1.5 — headless CLI regressions and source suites

- `test_copied_binary_headless_cli_without_display_variables` runs the copied
  binary with `DISPLAY`, `WAYLAND_DISPLAY`, `WAYLAND_SOCKET` and
  `QT_QPA_PLATFORM` absent: `--help` lists `gui`, and `init`, `status` and
  `export` succeed with no Qt/display startup.
- The direct documented invocation is now
  `uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' pytest -q
  tests`; source operation/parity suites and the offscreen Qt widget cases run
  with the GUI dependency, while the public command still accepts only
  `wayland`.

### Task 1.7 — integrated checks

- `scripts/check.sh` builds the executable once, runs all frozen tests
  (`tests/test_standalone.py`, including the new GUI coverage), then the source
  suite with the GUI dependency. `tests/test_check_script.py` verifies the
  command order, that failing frozen tests/builds/missing uv exit nonzero
  without skipping, and that the real script runs the mandatory frozen GUI test
  functions with no skip/importorskip path.
- Final `./scripts/check.sh`: `== syntax`, `== cli smoke`, `== standalone`
  → **40 passed in 19.70s**, `== tests` → **392 passed in 4.89s**, exit 0.
  Artifact: 88,636,960 bytes, SHA-256
  `d4a83900b47299fa22265e3a250ba52a4a54cd15436ff3542e1354160f7205ac`;
  `dist/longform-build.json` 36K, `dist/THIRD-PARTY-NOTICES.txt` 207K.
- Direct documented invocation from a clean state, with the fresh artifact
  reused rather than rebuilt: `uv run --with pytest --with httpx --with
  'pyside6>=6.12.0,<6.13' pytest -q tests` → **432 passed in 24.10s**.

## Task 1.6 — real copied-binary Wayland acceptance: PENDING

Not performed: this host has no Wayland session (`XDG_SESSION_TYPE=tty`,
`WAYLAND_DISPLAY` unset, no compositor socket). None of the following is
claimed: opening/reopening saved steering, editing a scene card, saving a manual
passage, export via the picker, window count, platform name, keyboard/mouse/
clipboard, resize, light/dark themes, or 100%/200%/fractional scaling. The task
remains unchecked. Offscreen widget tests and synthetic missing-socket startup
failures do not substitute for this desktop acceptance.

## Deviations and limits

- PySide6's Qt bindings are native CArchive entries, not PYZ modules; archive
  assertions check both places explicitly.
- Qt aborts at native plugin failure instead of raising a Python exception; the
  accepted contract is a nonzero exit plus already-flushed recovery advice.
- The LGPLv3/GPLv2/GPLv3 texts are vendored canonical SPDX files because the
  pinned PySide6/Shiboken wheels contain no license files. The notices record
  upstream licensing but do not by themselves authorize redistribution.
- Automated checks do not prove a working frozen window or compositor
  interaction. No desktop, older-distribution, musl, other-OS or universal
  support is claimed.
