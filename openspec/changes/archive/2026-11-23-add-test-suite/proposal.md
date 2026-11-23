# Proposal

## Why

The CLI now has syntax and help checks, but they cannot detect broken continuation
cleanup, lore matching, prompt settings, branch handling, or streamed responses.
Offline regression tests are needed before moving code out of this prototype.

## What Changes

- Add pytest tests for deterministic helpers, temporary-project tree operations,
  the deterministic checker, and API requests/streaming through mocked HTTP.
- Extract only the check report calculation from `cmd_check` into an in-script
  pure helper; keep its command output and saved report unchanged.
- Use the existing `scripts/check.sh` test-discovery path, not another runner.
  New tests are necessary because its existing syntax/help checks cannot assert
  these behaviors and no regression suite exists.

## Capabilities

### New Capabilities

- `offline-regression`: deterministic, discoverable CLI regression checks without
  credentials or live API requests.

### Modified Capabilities

None.

## Impact

Adds `tests/` and a small extraction inside `longform.py`; pytest/httpx are supplied
by uv for tests without changing runtime dependencies. Requires the tracked source
and real check script from `chore/testing-foundation` (commits `09bb632`, `2609c34`).

## Out of Scope

Packaging, broad core extraction, new writing features, live Featherless validation,
private sample/preset fixtures, and CI uv installation (a separate roadmap item).

## Demo

Run `uv run --with pytest --with httpx pytest -q tests`: expect collected tests and
`N passed`, exit 0, with no live requests. Run `./scripts/check.sh`: expect
`== syntax`, `== cli smoke`, `== tests`, and the same passing suite.
