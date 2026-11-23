# Proposal

## Why

The unshipped desktop branch now supports Create through completed drafting, but writers still need the terminal for continuity, review, revision, status and export. Milestone 3 is selected for proposal so these remaining CLI features can become buttons without changing the writing rules.

## What Changes

- Update-state and summary-only: detailed/brief previews, state diff, raw correction, edit/regenerate/accept/quit, warnings and existing backups/history.
- Compress: validated scene ranges, overlap/Replace confirmation, preview/edit/regenerate/accept/quit and saved arcs.
- Critique and deterministic scene/all checks: background progress/Stop, report viewing and built-in review-note editing/saving.
- Revise: passage-by-passage diffs, accept/skip/edit/regenerate/quit, existing history and stale-summary warnings.
- Read-only full status and destination-picked Markdown export with overwrite confirmation.
- Extend shared operations and the one worker, keeping CLI prompts/files/transcripts compatible, explicit acceptance and dirty/stale protection.

## Capabilities

### New Capabilities

- `desktop-continuity-review`: continuity, reports, revision, status and manuscript export from the existing desktop workspace.

### Modified Capabilities

None.

## Impact

Extract existing `cmd_*` behavior into Qt-independent review operations; extend `gui_window`, its current worker dispatch, safe snapshots and offline tests. Existing draft/planning operations cannot handle these commands because continuity/review/export orchestration still lives in terminal-bound `cmd_*` functions. No dependency, schema or ADR change; follow ADR-0007.

Out of scope: implementation in this proposal, shipping, new writing/provider policies, formats, restore engines or concurrent writers.

After implementation: run `QT_QPA_PLATFORM=wayland uv run --script longform.py gui DIR`; from a completed scene, accept continuity, compress, critique/check, accept/skip revisions, inspect status and export via a desktop picker. Expect saved reports/history and a path/word-count confirmation for CLI-equivalent `manuscript.md`. Audit the whole roadmap parity matrix afterward; Wayland acceptance remains separate.
