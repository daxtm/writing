# Proposal

## Why

The terminal hides saved swipes and branches behind commands and short previews.
Writers need a continuously available reading window while drafting.
Existing `draft` views and `export` cannot provide this: export includes only
the active manuscript, and neither keeps every saved branch readable in a browser.

## What Changes

- Add `view DIR [--port N] [--no-browser]`, a read-only browser reader served
  only on `127.0.0.1`, using the Python standard library.
- Show project progress, active scene text, every saved branch and its metadata,
  and retained trees without current scene cards.
- Show the bible, continuity state, scene/arc summaries, checks, and critiques.
- Refresh saved content automatically without terminal commands or a build step.
- Escape writing as plain text, allowlist readable content, and never expose
  configuration secrets or write endpoints.

## Capabilities

### New Capabilities

- `local-reader`: Browse and refresh saved project writing and all draft branches
  through a loopback-only, read-only web reader.

### Modified Capabilities

None; offline regression requirements remain unchanged.

## Impact

Implementation will extend the existing CLI dispatcher and reuse project/tree
semantics, adding `longform_core/web.py` and offline reader tests. No dependency,
project-format, launcher, or provider changes. ADR-0004 records the architecture.

Out of scope: browser editing/generation, authentication, multiple users, remote
hosting, rich text, packaging, deleted content recovery, and live token streaming.

Demo: `uv run --script longform.py view /path/to/project --no-browser --port 0`
prints `Reader: http://127.0.0.1:<assigned-port>/`. Open that URL to read project
progress, select a scene, read active and inactive branches, and see newly saved
drafts appear within the next two-second refresh cycle. Ctrl-C stops serving.
