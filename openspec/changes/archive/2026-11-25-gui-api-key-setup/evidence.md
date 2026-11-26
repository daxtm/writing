# Evidence — gui-api-key-setup

All commands run from the repository root on `feat/guided-workflow`.
Synthetic sentinels only: `sk-session-sentinel-credentials` (session),
`sk-project-sentinel-credentials` (saved project), `sk-env-sentinel-credentials`
(environment). No live API call anywhere.

## Task 1.1 — failing regression first

Command (at baseline `a37b055`, before any credential change):

```
uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' \
  python tests/qt_widget_cases.py case_credentials_session
```

Result: `FAIL case_credentials_session` with
`KeyError: 'credential_entry'` — the Setup tab had no masked entry, no
Use-for-this-session action and no source/availability status. The case was
registered in `tests/qt_widget_cases.py` `CASES` before the GUI existed, so the
unregistered-case guard kept it enforced.

## Task 1.2 — precedence chain

```
uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' \
  pytest -q tests/test_api.py tests/test_planning_ops.py \
           tests/test_review_ops.py tests/test_draft_parity.py
```

Result: `203 passed in 0.90s`. New coverage: `Api(p, session_key=…)` wins over
project `api_key` and `FEATHERLESS_API_KEY` for every role/family
(Authorization header and injected factory propagation), config and environment
are never mutated, `settings_state` no longer exposes `env_value`, and the
no-override CLI fixtures are byte-identical to the pre-change behavior.

## Task 1.3 — credential-only save op

```
uv run --with pytest --with httpx pytest -q tests/test_planning_ops.py
```

Result: `107 passed`. `plan.save_credential(root, action, value)` stores and
replaces a trimmed `api_key`, `clear` writes an empty string, empty value is
refused for save/replace but accepted for clear, unknown action is refused,
stale baseline / invalid JSON / missing project / symlinked destination
refusals leave `project.json` byte-identical, cancellation (`CancellationToken`
pre-cancelled) writes nothing, unrelated fields survive exactly.

## Task 1.4 — session controls and lifecycle

```
uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' \
  python tests/qt_widget_cases.py case_credentials_session
```

Result: `ok  case_credentials_session`. Observed: masked entry (echo mode
`NoEcho`), Use for this session flips status to
`Available — session key for this window…` and enables outline generation
without touching `project.json`, inert typing and empty input refuse with
guidance, the saved project key is the fallback source when no session exists,
a second window never inherits the session, close clears it, a cancelled Open
keeps the current session, a successful switch to another project clears it,
and every lifecycle step makes zero provider calls (`fake.calls == []`).

## Task 1.5 — storage controls

```
uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' \
  python tests/qt_widget_cases.py case_credentials_storage
```

Result: `ok  case_credentials_storage`. Observed: Save/Replace confirmation
names the plaintext/sharing-backup warning before any write, only `api_key`
changes in `project.json`, the entry clears only on success settlement, a
declined or stale save keeps the entry and the disk bytes, Clear saved writes
an empty `api_key`, a reopened window reports `Available — saved project.json
api_key` (never the value) or `Missing`, unrelated dirty settings go through
the existing Cancel/Discard resolver (a cancelled credential save keeps the
edits, a Discarded save persists only `api_key`), an external configuration
change between action and write is refused with reload guidance, and all five
credential buttons are disabled while any operation runs. The session-default
vs plaintext-saved distinction is printed in the group help text next to the
controls; normal Save settings never persist typed credentials.

## Task 1.6 — explicit connection test

```
uv run --with pytest --with httpx pytest -q tests/test_planning_ops.py
uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' \
  python tests/qt_widget_cases.py case_credentials_connection
```

Results: headless `107 passed`; offscreen `ok  case_credentials_connection`.
Observed: missing credentials produce recovery guidance
(`no API key … Use for this session …`) with zero provider calls; with a
session credential the button performs exactly one `GET /plan`, names the
winning source on success (`Connection succeeded using session credentials…`),
discards the response content and writes nothing (`limits.json` absent,
`project.json` byte-identical, `fake.started == 0` — no generation); a failing
lookup reports a sanitized failure (credential echoes replaced by
`[redacted]`); with the lookup blocked in flight, close offers Stop and wait,
the worker settles cooperatively, exactly one lookup ran, the window closes,
and nothing was written. All credential buttons are disabled while the lookup
runs.

## Task 1.7 — redaction boundaries

```
uv run --with pytest --with httpx pytest -q tests/test_api.py \
           tests/test_review_ops.py tests/test_draft_parity.py
uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' \
  python tests/qt_widget_cases.py case_credentials_redaction
```

Results: headless `203 passed`; offscreen
`ok  case_credentials_redaction`. Observed: a streamed answer whose synthetic
session key is split across two chunks never appears in the provisional
preview (`The key is [redacted] end. …`) nor in the accepted tree node file;
saved-project and environment sentinels are absent from previews, saved
artifacts, status text and reprs; a provider failure message echoing the saved
key is scrubbed at the worker boundary (`OpThread` now redacts through the
window's secret set) before it becomes an OpError/status; API error, stream
and log boundaries redact all known sources; `fetch_limits` metadata and the
redaction-aware `_scrub_text` paths keep ordinary CLI prompt/output/file
parity exact (the parity suites are unchanged and green).

## Task 1.8 — full check run

```
./scripts/check.sh
```

Result: passing end to end. Stages observed: `py_compile` clean; CLI
`--help` through uv; `== standalone` builds `dist/longform` and the frozen
executable tests pass (`45 passed in 27.36s`); source pytest `456 passed in
6.54s`, including `tests/test_qt_cases.py` running all 43 registered offscreen
cases (the four new credential cases among them). The
`tests/test_qt_cases.py` registration/runtime guard and
`tests/test_check_script.py` failure-propagation guard are unchanged.

```
uv run openspec validate --all --strict
```

Result: `Totals: 12 passed, 0 failed (12 items)`.

## Real Wayland acceptance — PENDING

Native Wayland verification of the masked entry (echo behavior, focus,
paste/clipboard, IME), the credential status labels at native DPR/scale, and
Test connection Stop/close under KWin is **PENDING**. It is a separate owner
desktop step, as in the previous GUI changes; nothing here infers it from
offscreen results, and no shipping or workspace-completion claim is made.
