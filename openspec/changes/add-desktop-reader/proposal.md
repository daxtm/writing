# Proposal

## Why

The owner rejected the unimplemented HTML reader and wants a real native GUI
alongside terminal drafting. Existing `draft`, `status`, and `export` commands
cannot provide a persistent desktop view of every saved branch and its notes.

## What Changes

- Add `gui DIR`: a blocking, read-only Tkinter/ttk desktop window, using the
  CLI's uv runtime and no new dependencies.
- Show scenes and retained trees on the left; Manuscript, Branches, and Notes
  tabs on the right, with full inactive text, metadata, navigation, and history.
- Add manual/two-second automatic refresh, preserved reading position,
  refresh time, totals, readable typography, and keyboard shortcuts.
- Load allowlisted writing through display-independent snapshots that tolerate
  optional missing/bad files without exposing configuration or credentials.
- Delete the rejected `add-reader-gui` proposal, supersede ADR-0004 with
  ADR-0005, and replace roadmap Phase 4; no web feature shipped.

## Capabilities

### New Capabilities

- `desktop-reader`: native, read-only browsing of saved scenes, branches, and
  notes with safe loading and position-preserving refresh.

### Modified Capabilities

None.

## Impact

Extend existing argparse dispatch before shared `Project` construction; add
`longform_core/reader_model.py` and `longform_core/gui.py`. Reuse `Tree.text()`
and `words()` semantics and existing pytest discovery in `scripts/check.sh`.
Keep the thin launcher and project formats unchanged.

## Out of Scope

Editing/generation, provider calls, server/browser/HTML interfaces, remote
access, rich-text rendering, secrets/config viewers, unsaved token streaming,
new dependencies, and Tk installation.

## Demo

After implementation: `uv run --script longform.py gui /path/to/project`.
Expect a native project-titled window with scene list and three reading tabs;
F5 refreshes, saved swipes appear automatically, and Ctrl+Q closes the window
and returns to the terminal. The command is not implemented by this proposal.
