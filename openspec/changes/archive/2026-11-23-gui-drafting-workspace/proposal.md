# Proposal

## Why

The implemented Qt shell can read and save steering, but cannot write a passage. The owner's finish line is every CLI/TUI feature in the GUI, start to finish; drafting alone is not completion.

Existing `cmd_draft`/`pick_candidates` already implement the writing rules, but their terminal prompts, printing and external editors cannot serve responsive desktop controls; extract those operations there rather than create another writing engine.

## What Changes

- Consolidate `gui-steered-drafting` and `gui-draft-controls` into this complete draft-loop workspace.
- Enable Generate with saved steering, default swipes or N candidates, progressive output, reroll/add/view, explicit Accept, keep/discard and eligible deletion.
- Add one background worker, cooperative Stop, safe close, stale-write refusal and usable reading during work.
- Expose passage length/token cap, POV/cast, scene card, budget/samplers/injected lore/exact prompt, scene completion, manual writing, edit/history, rewind/jump, full branch metadata, lore toggles/classification/aliases and file-picker imports.
- Preserve CLI prompts, sampling, histories, acceptance paths and files behind offline parity and button-flow tests.

## Capabilities

### New Capabilities

- `desktop-drafting`: Complete author-controlled drafting through the existing Qt workspace.

### Modified Capabilities

None.

## Impact

Build will change draft orchestration, API cancellation/event seams, Qt controls, reader refresh and offline tests/check integration. No dependencies or file-format migrations; ADR-0007 governs shared operations and the worker.

## Out of scope

Setup/planning and continuity/review/export controls remain two later changes. No implementation or shipping in this proposal; no terminal automation, concurrent writers or new provider capabilities.

## Demo after implementation

`QT_QPA_PLATFORM=wayland uv run --script longform.py gui DIR`

In an existing planned project, type steering, Generate two candidates, read progress, reroll/add, view and Accept one; edit/rewind/switch branches, import lore, inspect the prompt and mark done. Reopen: accepted text, branches, history and steering persist. Stop/failure never accepts or saves partial prose.
