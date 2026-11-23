# Tasks

## 1. Copyable executable

- [x] 1.1 Add a failing owner-journey test in `tests/test_standalone.py`: build through the documented script, copy only `longform` to a temporary path with spaces, remove Python/uv and source import paths, and run help/init from elsewhere. Add the test-only native network guard and its denial challenge alongside this test; verify the journey initially fails because no build script/artifact exists, never because it silently skipped or reached the network.
- [x] 1.2 Add the pinned build requirements and `scripts/build-standalone.sh` using the existing launcher, PyInstaller one-file console mode, explicit certifi data collection, and ignored `build/standalone/`/`dist/` outputs. Document build/copy/run and prerequisites in `docs/standalone.md`; verify 1.1 passes, artifact inspection finds runtime modules/SSL/CA data but no private inputs, and missing prerequisites or build errors exit nonzero.
- [x] 1.3 Generate `longform-build.json` and complete `THIRD-PARTY-NOTICES.txt` beside the executable; extend documentation and adjacent tests for the recorded source/runtime/dependency identity, native host-library boundary, license texts, and executable `TMPDIR` workaround. Verify the copied binary still runs without either informational sidecar and extracted CA data loads into a verifying SSL context without network.

## 2. Existing-command parity

- [x] 2.1 Add failing tests for frozen external-editor library-path leakage, then fix only the existing `edit_text` subprocess environment boundary. Verify both original-library-path cases, unchanged source behavior, and an offline scripted draft edit/save through the actual binary with a fake editor; document that editors remain user-supplied.
- [x] 2.2 Extend guarded copied-binary tests to compare first/repeated init, status, deterministic check reports, active-branch export, invalid arguments, and missing-key limits against the source CLI using synthetic fixtures. Verify matching files/output/exit statuses after only documented normalization, no writes to bundle/extraction paths, no network denial markers, and unchanged existing mocked API/credential tests.

## 3. Project check integration

- [x] 3.1 Extend `scripts/check.sh` to provision dependencies, print `== standalone`, and build once for all frozen tests while retaining syntax/help/source tests and network guards. Update check instructions in `AGENTS.md` and `docs/standalone.md`; verify the direct pytest invocation and `./scripts/check.sh` run the new coverage without skips, injected build/test failures fail checks, and the full supported-host run passes.
