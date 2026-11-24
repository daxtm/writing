# Proposal

## Why

Fifteen equal-priority tabs and always-visible drafting controls hide the next
step from a new writer. Existing actions already cover the writing loop, so
the window needs focused navigation rather than another writing engine.

## What Changes

- Reorganize the current window into Plan → Write → Review → Export, with
  project overview, saved-artifact readiness and one primary next action.
- Move draft Generate/count/steering into Write; group advanced actions in
  named secondary panels without removing any CLI-equivalent action.
- Preserve working previews, dirty edits, selection, read-only browsing and
  the existing one-operation Stop/close lifecycle across stage changes.
- Re-audit the complete parity map and cover keyboard/focus/labels, empty/error
  states, resizing, scaling and palette readability.
- Extend existing panes because the current tab arrangement cannot provide
  stage-specific guidance; no new application shell is needed.

## Capabilities

### New Capabilities

- `desktop-workflow`: guided stage navigation with complete advanced-action access.

### Modified Capabilities

- `desktop-reading`: stage-aware reading/steering layout and refresh preservation.

## Impact

Primarily `gui_window.py`, existing read-only overview helpers, Qt cases and
the roadmap parity map. ADR-0007/0011/0012 remain fixed; no new dependency,
schema or architectural ADR. Depends on credentials and streaming before
reparenting their controls. Full init is already implemented; the wizard follows.

Out of scope: setup wizard, automatic paid pipelines, mandatory review/export
gates, prompt/sampler/file changes, new engine features and shipping.

After implementation, run
`QT_QPA_PLATFORM=wayland uv run --script longform.py gui ./demo`.
Four primary stages replace the tab wall; Plan names missing inputs, Write
alone shows draft steering/Generate, and Review/Export remain deliberately
accessible with advisory readiness warnings.
