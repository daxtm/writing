# Proposal

## Why

Create now initializes complete files, but separate planning forms still leave
a beginner to discover the setup order. A resumable guide must compose those
existing actions without generating or accepting work on the writer's behalf.

## What Changes

- Make Create enter location/title/defaults → credentials → local bible
  answers → generate/choose outline → generate/edit/accept scene cards →
  first unfinished scene, with Back/Next and Save and resume later.
- Reopen guidance from Plan; derive readiness/resume from saved artifacts and
  existing answer histories, not a wizard-owned document.
- Reuse masked credentials, live previews, explicit paid actions/acceptance,
  dirty Save/Discard/Cancel and downstream replacement/history safeguards.
- Keep manual/advanced planning reachable and record real Wayland acceptance
  separately from the offline interrupted/reopened journey.
- Existing forms supply the operations but no sequenced resume guidance, so
  add only their wizard presentation, not new planning/provider logic.

## Capabilities

### New Capabilities

- `guided-project-setup`: resumable author-controlled setup through first writing.

### Modified Capabilities

None.

## Impact

Extends `gui_window.py` Create/deferred-Create and planning presentation using
shared init/settings/bible/outline/scenes operations and the one worker.
ADR-0007/0010/0011/0012 are fixed. Full init is already implemented; credentials,
streaming and navigation must land before this change.

Out of scope: AI bible calls, automatic paid generation, wizard-only project
formats, new dependencies, prompts/samplers/parser changes and shipping.

After implementation, run
`QT_QPA_PLATFORM=wayland uv run --script longform.py gui ./new-project`.
Choose Create, follow labelled steps, save/leave/reopen and continue from saved
work; explicit outline/scenes acceptance leads to Write at the first unfinished
scene without terminal/config/preset knowledge.
