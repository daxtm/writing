# Standalone executable (Linux x86_64, glibc)

`scripts/build-standalone.sh` freezes `longform.py` — the full CLI **and** the
native Qt Widgets GUI — into one copyable executable, `dist/longform`, using
PyInstaller one-file console mode. It bundles the Python 3.11 interpreter, the
current CLI and `longform_core`, the httpx dependency closure, certifi's TLS
certificate data, and the PySide6/Qt GUI runtime with its Wayland platform
plugins. The source/uv launcher remains fully supported; both entry points run
the same commands with the same arguments, prompts, credentials, and project
files, and the same native-Wayland-only policy.

## Prerequisites (build host)

- Linux x86_64 with glibc **2.34 or newer** (the pinned PySide6 wheels are
  `manylinux_2_34`; musl and other OSes/architectures are not built).
- `uv`, with a provisionable Python 3.11 (`uv python install 3.11` is run for
  you if needed).
- Network access **for provisioning build dependencies only**; the built
  application never installs or downloads anything.
- Build dependency versions are fully pinned in
  `scripts/standalone-requirements.txt` (`pyinstaller==6.22.3`,
  `pyinstaller-hooks-contrib==2026.10`, `pyside6-essentials==6.12.0`,
  `shiboken6==6.12.0`, and the pinned `httpx==0.28.1` closure); a rebuild
  re-provisions exactly those versions. The Qt bindings are pinned as
  `pyside6-essentials` because the GUI imports only QtCore/QtGui/QtWidgets and
  the Wayland platform plugins; the source range `pyside6>=6.12.0,<6.13` is
  unchanged.
- Running the frozen tests (`tests/test_standalone.py`, included in
  `./scripts/check.sh`) additionally requires a C compiler providing `cc` for
  the test-only native network guard.

## Build

```
./scripts/build-standalone.sh
```

The script diagnoses missing uv, unsupported OS/architecture/libc, and an
unusable build Python, and exits nonzero on any error. It prints the artifact
path on success. Generated spec/work files live under `build/standalone/` and
the executable under `dist/`; both are git-ignored. The build runs from the
repository root resolved from the script location. Build output is not
guaranteed to be bit-identical between runs; the interpreter patch version is
recorded in `dist/longform-build.json`. The current Qt 6.12.0 build produces an
executable of roughly 85 MB (212 MiB unpacked).

## Copy, run, distribute

```
cp dist/longform /wherever/you/want/
cd /any/other/dir && /wherever/you/want/longform --help
/wherever/you/want/longform init ./demo
/wherever/you/want/longform gui ./demo
```

Only the executable file is needed; the informational sidecars described below
are not required to run it. Relative paths (project directories, `--out`,
presets) resolve against the caller's working directory exactly as in source.

The GUI is the default entry point: running the executable with **no
arguments** — for example by double-clicking it in a file manager — opens the
GUI in the current directory. `gui` without `DIR` does the same. If that
directory is not a project, the window's Create/Open controls let the writer
choose or initialize one; nothing is written until an explicit Create/Open.

The GUI starts only in a native Wayland session, selected with
`QT_QPA_PLATFORM=wayland` (the command sets this itself when unset). Every other
value — `xcb`, `offscreen`, or fallback lists such as `wayland,xcb` — is
refused before Qt loads, and there is no XWayland or offscreen fallback window.
The executable must therefore run inside the Wayland session with the
compositor's socket available; check `$XDG_RUNTIME_DIR` and `$WAYLAND_DISPLAY`
as for any Qt Wayland application.

Two files are generated beside the executable for distribution purposes:

- `dist/longform-build.json`: the source revision and dirty state, OS,
  architecture, glibc, interpreter and resolved dependency versions, PySide6,
  Shiboken and Qt versions, the actual bundled plugin inventory, per-file `ldd`
  inspection of the Qt/Wayland libraries and plugins (bundled versus remaining
  host dependencies), native shared-library requirements of the executable
  itself (`ldd`), and artifact checksum.
- `dist/THIRD-PARTY-NOTICES.txt`: license texts for the bundled Python runtime,
  the bundled distributions (including certifi's CA data), the PyInstaller
  bootloader exception, and the LGPLv3/GPLv2/GPLv3 texts governing PySide6,
  Shiboken and Qt (vendored canonical SPDX texts, because those wheels ship no
  license files), plus the bundled plugin inventory.

## What is bundled vs. what stays on the host

- **Bundled**: the Python runtime, `longform.py` + `longform_core`, the httpx
  dependency closure, certifi's CA data, PySide6/Shiboken and the Qt libraries
  and plugins needed by the GUI (the Qt Wayland platform plugin, shell
  integrations, decoration and graphics-integration clients), and their
  non-system dependency closure.
- **Not bundled**: glibc, the Wayland client/EGL/GL libraries (for example
  `libwayland-client.so.0`, `libEGL.so.1`, `libGL.so.1`), the loader, and the
  running compositor socket. `dist/longform-build.json` records this boundary
  per Qt file. A Wayland desktop with a working Qt 6.12 Wayland stack is
  required on the host.
- Single-file does **not** mean static. The executable still needs a compatible
  Linux loader and standard system libraries on the target host; it was built
  and verified on one host, whose boundary is recorded in
  `dist/longform-build.json`. Running it on an older distribution is not
  guaranteed — build on the older baseline if you need it.
- An editor invoked by the `draft` loop is the user's own `$VISUAL`/`$EDITOR`
  program. In a frozen build, the child editor sees the host's original
  `LD_LIBRARY_PATH` (restored from `LD_LIBRARY_PATH_ORIG`, or unset when there
  was none), so the bundled runtime's private library path does not leak into
  it.
- Online commands (`limits`, `outline`, `draft` generation, ...) still require
  the same Featherless API key (`api_key` in project.json or the `api_key_env`
  environment variable) and the existing service. No command contacts an API
  automatically.

## Extraction and `TMPDIR`

One-file mode extracts the bundled runtime and Qt libraries into a temporary
directory (removed on exit), usually under `$TMPDIR`; expect roughly 212 MiB of
temporary storage while the executable runs. That directory must be on
**writable, executable** storage. If the default temporary mount is mounted
`noexec`, point `TMPDIR` at executable storage before running:

```
export TMPDIR="$HOME/tmp-exec"   # a writable, exec-allowed directory
"$longform" --help
```

Updates are done by rebuilding and replacing the executable (including
dependency and CA-certificate updates); there is no auto-updater.

## Testing

`./scripts/check.sh` prints `== standalone`, builds the executable once through
`scripts/build-standalone.sh` (provisioning build dependencies; may use the
network), runs `tests/test_standalone.py` against that artifact, and then runs
the source regression suite. The frozen tests cover GUI discovery/archive
content and startup-policy failures in addition to the CLI; they are
mandatory and fail — never skip — when the build, Qt, plugin, or compiler
dependencies are missing.

The direct documented pytest invocation is:

```
uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' pytest -q tests
```

It runs the same source suite and provisions/builds through the production
script whenever `dist/longform` is missing or older than the build inputs (the
frozen tests reuse a freshly built artifact rather than rebuilding). The
public `gui` command still accepts only native Wayland; `offscreen` is used
only inside the test subprocess for widget cases.

The copied binary is exercised away from the checkout (with Python/uv and the
source import paths absent) against synthetic projects, in parity with the
source CLI, under a native network guard that denies Internet access inside the
frozen process and its children (proven by a compiled challenge probe, without
Python on PATH). Missing compiler, missing build prerequisites, a failed build
or a failing frozen test fails the checks with a nonzero exit; nothing is
skipped. Source-side monkeypatch/sitecustomize network guards are retained for
the source runs.

Frozen GUI diagnostics name the executable itself:
`QT_QPA_PLATFORM=wayland /path/with spaces/longform gui DIR`, never `uv` or the
source launcher. A missing Wayland socket aborts inside Qt after this advice is
flushed; the contract is a nonzero exit plus the recovery guidance, not a
Python exception.

## Acceptance limits

Automated checks prove the archive contains the GUI closure and that startup
policy/advice works in the copied binary. They do **not** prove a working
frozen window. Real mouse/keyboard/clipboard/picker behavior, scaling, themes,
and the complete drafting/planning/review journey of the copied executable in a
native Wayland session require the separate desktop acceptance recorded in
`openspec/changes/standalone-gui/evidence.md`; it remains PENDING until an
owner runs it on a real desktop. Offscreen widget tests and archive inspection
do not substitute for it.

