# Evidence — project-defaults-full-init

## Task 1.1 baseline (recorded before initialization changed)

Command (against baseline `2d4cef2`):

```
uv run --with pytest --with httpx pytest -q tests/test_init_defaults.py
```

Result: `1 xfailed in 0.06s` — the strict `xfail` regression
`test_cli_init_without_preset_creates_complete_defaults` fails exactly as
expected: baseline `init DIR` with no preset selection creates only the five
existing files (no `writer_preset.json`), so the `created:` line and the
preset-usability assertions fail. The xfail is strict, so it becomes an error
the moment the behavior exists without the marker being removed.

After task 1.4 the marker is removed and the same test must pass unmarked.

Task 1.4 follow-up: the marker was removed and the suite reports
`431 passed` (source stage, standalone excluded); the CLI transcript is frozen
as `created: project.json, bible.md, state.md, scenes.json, summaries.json,
writer_preset.json`, failures exit nonzero via `die()`/`FatalError` with
truthful partial-work diagnostics, and explicit `--preset` copies exact bytes.

Task 1.6: the deferred Create/Open continuation was dead code — `_resolve_dirty`
returned False for both cancel and a dispatched save, and the callers cleared
`_pending_action` on False, so the settings-save settlement never resumed. The
resolver now returns `ok`/`cancel`/`deferred`, Create/Open pick the target
first and keep `_pending_action` across the deferred save, cancelled/stopped
operations clear the pending transition, and a stopped initialization reports
completed writes with retry-fills-missing semantics. Covered by the registered
offscreen case `case_planning_deferred_create` (save-before-init, no
old-project inheritance, immediate/deferred byte agreement, cancelled
resolution, stale-save refusal, Stop then retry).

Task 1.7: `scripts/build-standalone.sh` packages `longform_core/resources`
only (`--add-data longform_core/resources:longform_core/resources`) and passes
the same flag to the sidecar generator; `scripts/standalone_sidecars.py`
verifies the two reviewed assets are present in the archive (fail-closed at
build time) and records name/size/SHA-256 provenance in
`dist/longform-build.json` (`bundled_resources`) and
`dist/THIRD-PARTY-NOTICES.txt` (hashes only, never contents, no private
source fragments). The frozen-test freshness input list now includes
`longform_core/resources/*.json`; `docs/standalone.md` documents the bundled
defaults, override/no-overwrite semantics and provenance sidecars. Frozen
coverage: archive TOC resource bytes equal the repository assets exactly,
copied-binary init creates the six files/seven directories with bundled
defaults and empty `api_key`, repeat init preserves an existing preset,
explicit synthetic `--preset` wins for a missing destination and is refused
with a warning for an existing one, invalid JSON/unreadable preset sources
fail closed (nonzero, partial-work note, no preset), and
frozen/source parity covers init, repeat, explicit preset, invalid preset,
missing preset source and preset-restore-after-removal
(`test_parity_init_first_and_repeated`, `test_parity_init_with_preset`,
`test_parity_init_explicit_preset_failure_and_missing_source`,
`test_parity_init_preset_restore_after_removal`).

## Handoff (stopping point, session end)

- Completed and pushed: 1.1 (`tests/test_init_defaults.py` baseline, later
  unmarked), 1.2 (`defaults.py`, resources, docs, `tests/test_defaults.py`),
  1.3 (`91f91e2`), 1.4 (`165267e`), 1.5 (`e783b87`), 1.6 (`a137fef`),
  1.7 (commit following this note).
- Current state: working tree clean; `./scripts/check.sh` passes end to end
  (py_compile, `--help`, standalone build + 45 frozen tests, source pytest
  433 passed) with no skips; branch `feat/project-defaults-full-init` synced
  with origin.
- Exact next task: **1.8** — run `./scripts/check.sh` to a passing result and
  record commands/results here, record the real-Wayland
  Create/reopen/dirty-Save walkthrough (or leave it explicitly PENDING), then
  commit/push.
- Remaining tasks: 1.8 only.
- Failing/pending checks: none failing; real-Wayland desktop acceptance
  (Create/reopen/dirty-Save walkthrough) remains **PENDING** and is not
  claimed by the offscreen cases. Do not ship or merge.
