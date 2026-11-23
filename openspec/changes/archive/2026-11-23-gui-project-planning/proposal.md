# Proposal

## Why

The implemented Qt draft loop still needs a project prepared in the terminal. The owner has selected milestone 2 so a writer can create a project and reach a scene entirely through desktop controls.

Existing commands own these rules but mix them with terminal questions, external editors and blocking provider calls; extract their operations rather than automate the terminal or introduce another writing engine.

## What Changes

- Create/Open directory dialogs, non-overwriting initialization and validated SillyTavern preset import.
- Supported nonsecret settings, credential-variable availability only, and explicit Fetch limits with results/errors.
- Bible fixed-question multiline forms, preview/edit/accept/skip/leave, section editing, saved answers and history.
- Outline notes, N competing planner candidates, view/reroll/choose/edit and backed-up saves.
- Scene generation, card previews/editing/validation, confirmed replacement with backups, and entry into the existing draft loop.
- Shared Qt-independent operations, unchanged applicable CLI prompts/files/transcripts, one existing worker, cooperative Stop, safe paths and stale-input refusal.
- Headless, fake-provider parity and offscreen button-flow coverage in `scripts/check.sh`; separate real Wayland acceptance.

## Capabilities

### New Capabilities

- `desktop-project-planning`: Desktop creation, configuration and author-controlled planning through saved scene cards.

### Modified Capabilities

None.

## Impact

Build will extend existing command/core boundaries, Qt window and worker adapters, and offline tests. No new dependency, provider endpoint or project format. ADR-0006/0007 already govern the approach.

## Out of Scope

Continuity/review/revision/status/export controls, new model capabilities, key entry/storage, terminal automation, shipping and whole-workspace completion. Do not create the review/export change yet.

## Demo After Implementation

Run `QT_QPA_PLATFORM=wayland uv run --script longform.py gui /path/to/new-project`. Create or Open via picker, import a preset, configure models, explicitly fetch limits, save bible answers, choose an outline and accept scene cards. Reopen: saved scenes appear and selecting one enables existing drafting when prerequisites are available; no terminal prompts.
