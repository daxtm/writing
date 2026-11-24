# ADR-0011: Deliver all generated answers through shared preview events

- Status: Accepted
- Date: 2026-11-23
- Related: docs/ROADMAP.md guided workflow milestone 1; gui-generated-text-streaming; ADR-0007

## Context
`Api._post` already requests streaming and invokes text callbacks; `Api.chat`
accepts stream_cb. Drafting displays a single candidate progressively, whereas
chat_many and planning/review callers mainly emit completion/progress events.
The GUI's one background worker already queues operation-identified events.
The owner requires all generated text to appear before completion, including
multiple candidates, without changing final parsing or acceptance rules.

## Options
1. Add a GUI-only network client or poll call logs for partial output — leaves
   current operations alone but duplicates provider behavior or couples previews
   to logs and cannot reliably isolate concurrent candidates/retries.
2. Extend existing API callbacks, batching and shared-operation events — reuses
   transport/cancellation and final outputs but requires consistent event routing.

## Decision
Choose option 2 because the transport already streams; the missing boundary
is delivery of answer chunks through operations to their owning GUI previews.
Use the existing one worker and queued event mechanism. Add stable operation,
candidate and retry-attempt identities and start/delta/reset/complete events
where needed, covering chat and text completion and all generated-text callers.
Retain default CLI behavior when preview subscribers are absent.

Show waiting/thinking status until answer text arrives; do not render hidden
reasoning as accepted answer text. Stream previews are provisional, including
incomplete JSON/tags. Final results still pass through existing reasoning
separation, cleaning, validation, history/save and explicit acceptance rules.
Retry resets the failed attempt only; cancellation/failure cannot accept or
save fragments. Completed candidates retain existing save semantics.
GUI event handling may coalesce queued deltas for responsiveness, but must
display received answer text before the response finishes and never combine
different candidates or attempts. Keep current provider concurrency limits.

## Consequences
- Good: one consistent live-preview contract covers planning, drafting and
  review without duplicated prompts, a new network stack or another job system.
- Good: paused fake streams can prove visible intermediate output offline.
- Bad: batching and retries need explicit identity tests, and incremental
  reasoning separation must handle delimiters split across chunks.
- Bad: provisional structured output may be temporarily invalid; the UI must
  distinguish it from editable/acceptable completed results.
