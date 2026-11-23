# Standalone executable (Linux x86_64, glibc)

`scripts/build-standalone.sh` freezes the existing `longform.py` CLI into one
copyable native executable, `dist/longform`, using PyInstaller one-file console
mode. It bundles the Python 3.11 interpreter, the current CLI and
`longform_core`, the httpx dependency closure, and certifi's TLS certificate
data. The source/uv launcher remains fully supported; both entry points run the
same commands with the same arguments, prompts, credentials, and project files.

## Prerequisites (build host)

- Linux x86_64 with glibc (musl and other OSes/architectures are not built).
- `uv`, with a provisionable Python 3.11 (`uv python install 3.11` is run for
  you if needed).
- Network access **for provisioning build dependencies only**; the built
  application never installs or downloads anything.
- Build dependency versions are fully pinned in
  `scripts/standalone-requirements.txt` (`pyinstaller==6.22.3`,
  `pyinstaller-hooks-contrib==2026.10`, and the pinned `httpx==0.28.1` closure);
  a rebuild re-provisions exactly those versions.
- Running the frozen tests (`tests/test_standalone.py`, included in
  `./scripts/check.sh`) additionally requires a C compiler providing `cc`.

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
recorded in `dist/longform-build.json`.

## Copy, run, distribute

```
cp dist/longform /wherever/you/want/
cd /any/other/dir && /wherever/you/want/longform --help
/wherever/you/want/longform init ./demo
```

Only the executable file is needed; the informational sidecars described below
are not required to run it. Relative paths (project directories, `--out`,
presets) resolve against the caller's working directory exactly as in source.

Two files are generated beside the executable for distribution purposes:

- `dist/longform-build.json`: the source revision and dirty state, OS,
  architecture, glibc, interpreter and resolved dependency versions, native
  shared-library requirements (`ldd`), and artifact checksum.
- `dist/THIRD-PARTY-NOTICES.txt`: license texts for the bundled Python runtime,
  the bundled distributions (including certifi's CA data), and the PyInstaller
  bootloader exception.

## What is bundled vs. what stays on the host

- **Bundled**: the Python runtime, `longform.py` + `longform_core`, the httpx
  dependency closure, and certifi's CA data.
- **Not bundled**: glibc and other system libraries (`ldd` records the
  host-library requirement), any external editor, and any API credentials.
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

One-file mode extracts bundled libraries into a temporary directory (removed on
exit), usually under `$TMPDIR`. That directory must be on **writable,
executable** storage. If the default temporary mount is mounted `noexec`,
point `TMPDIR` at executable storage before running:

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
the source regression suite. The direct documented pytest invocation,
`uv run --with pytest --with httpx pytest -q tests`, runs the same coverage: it
includes the frozen tests and provisions/builds through the production script
whenever `dist/longform` is missing or older than the build inputs (the frozen
tests reuse a freshly built artifact rather than rebuilding).

The copied binary is exercised away from the checkout (with Python/uv and the
source import paths absent) against synthetic projects, in parity with the
source CLI, under a native network guard that denies Internet access inside the
frozen process and its children (proven by a compiled challenge probe, without
Python on PATH). Missing compiler, missing build prerequisites, a failed build
or a failing frozen test fails the checks with a nonzero exit; nothing is
skipped. Source-side monkeypatch/sitecustomize network guards are retained for
the source runs.
