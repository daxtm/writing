# Design

## Context

See [proposal.md](proposal.md) for motivation. This branch starts from main:
`longform.py` imports/re-exports `longform_core`, and its `__main__` wrapper
already owns CLI dispatch and error handling. There is no integrated GUI here.
`cmd_init`, `cmd_status`, `cmd_check`, and `cmd_export` already work offline.
`edit_text` invokes an external editor through `subprocess.run`.
`scripts/check.sh` checks source; no existing distribution build exists.

The source tests block network with monkeypatches and a subprocess
`sitecustomize.py` on `PYTHONPATH`. A frozen interpreter cannot be assumed to
load that guard. Preserve it for source tests and separately guard native tests.

## Goals / Non-Goals

- Freeze the current entry point without changing prompts, dispatch, or files.
- Test the actual production executable copied away from source, not a wrapper
  that falls back to a development interpreter.
- Scope compatibility to Linux x86_64 glibc native builds. Other Linux system
  libraries remain host prerequisites, recorded rather than guessed away.
- Do not integrate the unmerged desktop branches, collect unused Qt/Tk
  dependencies, add installers, or change the roadmap's GUI milestones.

## Decisions

### 1. Freeze the existing launcher

[ADR-0008](../../../docs/adr/0008-standalone-native-executable.md) selects
PyInstaller one-file console mode over zipapp/runtime installation.
Use `longform.py`, including its existing exception handling; do not add a
second application entry point or change no-argument behavior to open a GUI.

Add `scripts/build-standalone.sh`. Resolve the repository from the script
location and build from that root. Use a Python 3.11 uv build environment with
`pyinstaller==6.22.3`, `pyinstaller-hooks-contrib==2026.10`, and `httpx==0.28.1`.
Keep a fully pinned build dependency closure in
`scripts/standalone-requirements.txt`, consumed through uv's requirements-file
support; do not add PyInstaller to PEP 723 runtime dependencies.
Record the resolved Python patch version; do not promise bit-identical builds.

Invoke `python -m PyInstaller` with `--onefile --console --name longform
--clean --noconfirm --noupx --collect-data certifi`. Put generated spec/work
files under `build/standalone/` and the final executable under `dist/`.
Ignore these output directories. Use explicit module/data collection, never
`--add-data .` or a checkout archive: no private projects, presets, `.env`,
tests, or credentials enter the artifact.
The normal PyInstaller analysis includes `longform_core` and httpx dependencies;
verify the bundled CA file and SSL extension rather than disabling verification.

The build script diagnoses missing uv, unsupported OS/architecture/libc, and
unusable build Python before producing success. It exits nonzero on errors.
Dependency provisioning can use network; the built application cannot
provision anything. It prints the artifact path on success.

### 2. State compatibility honestly

Produce `dist/longform-build.json` with source commit and dirty state, OS,
architecture, glibc, interpreter, resolved dependency versions, and native
shared-library requirements observed on the build host. Produce
`dist/THIRD-PARTY-NOTICES.txt` containing license texts for the bundled Python
runtime and distribution dependencies (including certifi's data), plus the
PyInstaller bootloader exception where applicable. Sidecars inform distribution;
they are not required for execution. Do not publish binaries in this change.

Add `docs/standalone.md` with native build prerequisites (uv, provisionable
Python 3.11, standard Linux loader/system libraries; `cc` for frozen tests),
copy/run examples, notices, and extraction behavior. `TMPDIR` must point to
writable executable storage when the default temporary mount is `noexec`.
Single-file does not mean static, no system libraries, no editor, or no API
credentials. Existing online commands still require the existing credentials
and service. No online command is invoked automatically.

The proposal host reports x86_64, glibc 2.44, Python 3.14.10, and uv 0.12.13;
these are observations, not a tested frozen runtime or a promised broad
distribution baseline. Build with the chosen 3.11 interpreter and record the
actual result. Claim only the verified native host/runtime boundary; an older
distribution would need a build on that older baseline.

### 3. Preserve external editor behavior at the existing boundary

Fix `longform_core.utils.edit_text`, not a separate frozen command layer.
For frozen execution only, pass an editor child environment that restores
`LD_LIBRARY_PATH` from `LD_LIBRARY_PATH_ORIG`, or removes it when no original
value exists. Do not mutate the parent environment or remove unrelated user
variables. Leave source execution unchanged. Test both original-path-present
and original-path-absent cases, including actual edit/save through the binary
with a fake editor and scripted draft input. Do not bundle an editor.

### 4. Test the copied production artifact without network escape

Add `tests/test_standalone.py`; build once per test session using the production
script, then copy only the executable into a temporary directory with spaces.
Run it by absolute path from a different working directory. Set PATH to an
empty test directory, unset `PYTHONPATH`, `PYTHONHOME`, credentials and trust
overrides, and ensure the source checkout is not a runtime resource. No
test-only hooks, commands, or fallback imports enter the production executable.

Add a test-only native `LD_PRELOAD` guard compiled with `cc`: deny Internet
socket creation/connection, datagram sends, and hostname resolution before they
reach the network, and emit a recognizable denial marker. Keep it active for
the bootloader, interpreter, and children; fail normal tests on that marker.
Use a small native challenge probe to verify denial, not Python on PATH.
This is additional native-process coverage, not a replacement for existing
monkeypatch/sitecustomize guards. Missing compiler/guard must fail explicitly.

Compare source/binary help (program name normalized), first/repeated init,
status, deterministic check reports, active-path manuscript export, invalid
arguments, and missing-key `limits`. Use fixed synthetic scenes/trees, including
inactive branches; normalize only roots, program name, and known fixture
timestamps. Validate credential lookup with existing synthetic mocked API tests,
not a live provider. Test editor environment cleanup in place and through an
offline scripted draft edit.

Inspect the built archive for bundled dependency modules, `_ssl`, and the
nonempty certifi CA data; exclude private/test inputs. Use a build-environment
SSL-context check against that extracted CA data to verify it parses and
verification remains enabled, without an HTTPS call. This is packaging/trust
data evidence, not live-provider TLS acceptance.

Extend existing `scripts/check.sh`, not a parallel check entry point: provision
build/test dependencies before offline tests, print `== standalone`, build once,
and run frozen tests against that artifact. The direct documented pytest command
must also provision the build prerequisites through the fixture/build script
and actually run frozen tests, not silently deselect them.

## Risks / Trade-offs

- [Newer glibc limits portability] → record the actual build boundary; no
  unsupported backwards-compatibility or musl claims.
- [Single-file extraction and startup overhead] → document executable `TMPDIR`
  and replacement-based updates rather than adding an installer.
- [Bundled dependencies age] → pin and record versions, include notices, and
  rebuild for dependency/CA updates; no auto-updater.
- [A frozen child bypasses Python test guards] → enforce native preload denial,
  challenge it, and retain the existing source guards.
- [Checks get slower and require `cc`] → build once per run, document the
  prerequisite, and never trade the acceptance test for a skip.

## Migration Plan

No project migration or default-entry-point change. Build and verify locally,
then copy `dist/longform` and carry its notices when distributing. Roll back by
replacing the executable or using the unchanged uv source launcher. No installer,
release workflow, branch integration, or shipping authorization is added.
