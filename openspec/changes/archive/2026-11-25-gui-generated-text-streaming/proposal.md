# Proposal

## Why

The transport already streams, but most planning/review previews and draft
batches wait for complete responses. Writers need visible answer text during
every request, with separate previews when candidates or retries overlap.

## What Changes

- Extend existing callbacks, batching and worker events to deliver answer
  start/delta/reset/complete updates with stable operation/candidate/attempt
  identities.
- Show waiting/thinking status and provisional raw structured output for
  outline, scene cards, draft, continuity, compression, critique and revision,
  including rerolls, additions and regenerations.
- Keep hidden reasoning out of answer previews, partial text out of accepted
  files, completed parsing/saves unchanged and unsubscribed CLI output frozen.
- Fix existing streaming seams; a GUI-only client or log polling is unnecessary.

## Capabilities

### New Capabilities

- `generation-previews`: live isolated answer previews across writing operations.

### Modified Capabilities

- `desktop-drafting`: replace completion-only batch progress with live previews
  for every candidate while retaining complete saved branches.

## Impact

Extends `api.py`, the three shared operation modules, `draft_worker.py` event
delivery and `gui_window.py` preview routing; no new network stack/dependency.
ADR-0007/0012 are fixed. Depends on `gui-api-key-setup` for credential-safe
delivery; `project-defaults-full-init` is already implemented. Navigation and
the wizard depend on this change.

Out of scope: AI bible answers, changed prompts/samplers/retry policy/final
parsers/file formats, CLI transcript changes and shipping.

After implementation, run
`QT_QPA_PLATFORM=wayland uv run --script longform.py gui ./demo`.
With saved bible answers and credentials, Generate two outlines: each labelled
preview gains answer text before its request finishes. Offline paused-stream
tests prove the same result without paid calls.
