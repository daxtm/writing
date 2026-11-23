# Evidence — standalone-executable

Host: Linux x86_64, glibc 2.44 (`ldd (GNU libc) 2.44`), uv 0.12.13, system
Python 3.14.10, uv-managed CPython 3.11.15, `cc` = /usr/bin/cc.

## Commands and results

### Task 1.1 (commit 36b7014, red by design)
- `pytest -q tests/test_standalone.py` → 2 errors at the `built` fixture:
  `scripts/build-standalone.sh not found`; guard/probe compiled with `cc` and
  challenged successfully (probe rc=0, stderr shows
  `LONGFORM-NETWORK-DENIED op=socket|connect|sendto|getaddrinfo|gethostbyname`).
  Failure is explicit, never a skip, and no frozen process reaches the network.

### Task 1.2 (commit 211e910)
- `./scripts/build-standalone.sh` → artifact `dist/longform` (12,178,920 B),
  smoke `--help` ok, sidecars later in 1.3. End-to-end ≈ 7.7–7.9 s including
  provisioning (`uv venv --clear --python 3.11` + pinned
  `scripts/standalone-requirements.txt`, PyInstaller 6.22.3 onefile console).
- Archive inspection via `build/standalone/venv/bin/python` +
  `PyInstaller.archive.readers`: CArchive contains `longform`,
  `libpython3.11.so.1.0`, `certifi/cacert.pem` (nonempty, >10,000 B), `PYZ.pyz`;
  PYZ contains `longform_core.*`, `httpx`, `httpcore`, `anyio`, `ssl`, `certifi`;
  `PyInit__ssl` bytes present in the extracted libpython (statically compiled
  `_ssl` on this toolchain). No private/test fragments (`myfic`, `tests`,
  `.env`, fixture/preset names) anywhere in the bundle.
- `env -i PATH=/usr/bin:/bin bash scripts/build-standalone.sh` → rc=1 with
  `uv not found` (missing prerequisites exit nonzero).
- `pytest -q tests/test_standalone.py` → 5 passed.

### Task 1.3 (commit a3d47bc)
- Build writes `dist/longform-build.json` (commit + dirty state from real git,
  Linux/x86_64/glibc 2.44, CPython 3.11.15, resolved deps: altgraph 0.17.5,
  anyio 4.16.0, certifi 2026.11.20, h11 0.16.0, httpcore 1.0.9, httpx 0.28.1,
  idna 3.20, packaging 26.4, pyinstaller 6.22.3, pyinstaller-hooks-contrib
  2026.10, setuptools 84.2.1, typing_extensions 4.16.0; artifact bytes+sha256;
  `ldd` of the artifact listing libc.so.6 etc.) and
  `dist/THIRD-PARTY-NOTICES.txt` (112,884 B: PSF Python license, every bundled
  distribution's license text incl. certifi MPL-2.0, PyInstaller GPL text with
  the Bootloader Exception).
- Tests: recorded identity vs real git/python state, license coverage, copied
  binary runs alone in a spaced dir (no sidecars present), extracted CA data
  loads into an SSL context with `verify_mode == CERT_REQUIRED` and >50
  certificates, no network call. `pytest -q tests/test_standalone.py` → 9 passed.

### Task 2.1 (commit 404d775)
- Red first: three editor tests failed (leak reproduced: frozen
  `LD_LIBRARY_PATH=_MEIPASS` reached the editor child). Fix in
  `longform_core/utils.edit_text`: frozen-only child env restores
  `LD_LIBRARY_PATH` from `LD_LIBRARY_PATH_ORIG` or removes it; parent
  environment never mutated; source execution unchanged (source test passes).
- Through the actual copied binary with a fake `$VISUAL` editor: draft `se` →
  edit → save works; editor dump shows `LD_LIBRARY_PATH=/host/original/lib`
  when ORIG was set, and `LD_LIBRARY_PATH_SET != set` when it was not.
  `pytest -q tests/test_standalone.py` → 13 passed; source suite 160 passed.

### Task 2.2 (commit 4d9258a)
- Guarded parity (copied binary vs `uv run --script longform.py` on separate
  synthetic projects; normalization limited to temporary roots, program name +
  argparse usage wrap, fixture timestamps): help, invalid command, missing
  required argument, missing project dir, first+repeated `init` (identical file
  sets/contents), `init --preset` (synthetic preset copied byte-identically),
  `status` with inactive branches, `check` (identical reports after stamp
  normalization; inactive-branch text absent), `export` (identical manuscript,
  inactive branch excluded, relative `--out` lands in the caller's cwd),
  `limits` without credentials (same diagnostics, no HTTP).
- Every frozen run asserts no network-denial markers, no extraction leftovers,
  and no writes to `dist/` or `build/standalone/`. `pytest -q tests` → 184 passed.

### Task 3.1 (commit 56a007d)
- `./scripts/check.sh` prints `== syntax`, `== cli smoke`, `== standalone`
  (builds once, runs frozen tests), `== tests` (source suite minus the frozen
  file). Full run: ≈ 12.6 s end-to-end on the supported host; `== standalone`
  24 passed, `== tests` 163 passed.
- Direct documented invocation `uv run --with pytest --with httpx pytest -q
  tests` from a clean state (`dist/` and `build/standalone/` moved away) →
  187 passed in ≈ 11.7 s; it provisioned/builds through the production script
  and reused nothing stale. With a fresh artifact present it reuses it
  (≈ 4.0 s total for the suite).
- Injected-failure proof: contract tests in `tests/test_check_script.py`
  (fake `python3`/`uv`, fake build script) verify the command order and that
  failing pytest (rc 3), failing frozen tests (rc 5), failing build (rc 7), and
  a missing build script make check.sh exit nonzero without reaching `== tests`.

## Deviations
- Task 1.1's commit is intentionally red (its content is the failing
  owner-journey test before any build script exists); all later commits are
  green and the final `ock check HEAD` passes.
- The bundled `_ssl` is statically compiled into `libpython3.11.so.1.0` on this
  toolchain (no separate `_ssl` extension entry), so the inspection test asserts
  `PyInit__ssl` bytes in the extracted libpython.
- `LD_LIBRARY_PATH` unset-vs-empty is asserted via the shell expansion
  `${VAR+set}` in the fake editor dump, because a child shell cannot
  distinguish an exported-empty variable from an unset one by `$VAR` alone.
- The native network guard compiled objects live in a session temp dir rather
  than under the project tree (test-only artifact, keeps the repo clean);
  source-side monkeypatch/sitecustomize guards are unchanged.
