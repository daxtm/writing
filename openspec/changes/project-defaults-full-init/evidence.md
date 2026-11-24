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
