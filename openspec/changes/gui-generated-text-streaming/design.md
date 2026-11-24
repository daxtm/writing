# Design

## Context

See proposal.md — Why. Full init is already implemented. Implement
`gui-api-key-setup` first for provider/redaction coverage, this change second,
then navigation and the wizard; do not redesign those interfaces here.

- `Api._post` already consumes streamed chat/text data and calls `stream_cb`
  with raw content; reasoning fields are collected separately. `chat` applies
  `split_thinking` only at completion. Existing callbacks can therefore expose
  inline reasoning if forwarded without separation.
- `chat`/`complete` retry callbacks differ; `complete` can also resubmit without
  rejected extras. Those attempts currently lack stable preview identities.
- `many` calls zero-argument functions and numbers completions, not logical
  requests. `chat_many` supplies no per-candidate text callback.
- `draft_operations.generate_candidates` streams only `count == 1`.
  `planning_operations.generate_outlines` uses `chat_many`; scene generation
  and all review generators call `chat` without answer callbacks.
- `OpThread` already queues `(op_id, payload)` and one terminal result.
  `MainWindow._on_worker_event` appends every delta to one `_preview_text`;
  `_on_worker_done`/`_on_thread_finished` own settlement. Keep that lifecycle.

## Goals / Non-Goals

**Goals:** isolated live answer previews before completion, compatible final
results and default CLI transcripts, deterministic paused-stream proof.

**Non-goals:** provider protocol changes, alternate client/worker, changed
prompts, sampling, parser/retry policy, incremental acceptance or AI bible calls.

## Decisions

### Extend callbacks and optional shared preview events

Follow [ADR-0012](../../../docs/adr/0012-shared-generation-stream-events.md)
and [ADR-0007](../../../docs/adr/0007-shared-writing-operations.md), with
credential delivery from [ADR-0011](../../../docs/adr/0011-gui-project-credentials.md).
Do not re-decide their architecture. Keep final return tuples and existing
progress events. Add an optional `preview_events` subscriber to relevant API/
operation entry points, separate from legacy `events`; GUI passes the worker
sink to both, CLI does not subscribe to the new stream.

That separation is important: `_cli_draft_events` already prints legacy N=1
stream_start/delta/stream_end; feeding new batch deltas to it changes transcripts.
With no preview subscriber, preserve current callback/progress/log behavior
and completion-order result lists. With a subscriber, suppress redundant
terminal progress, and emit typed preview events only through that subscriber.
Legacy GUI callbacks must not append the same answer twice.

Use this common event envelope (no credential/config/header objects):

| Field | Meaning |
|---|---|
| `type` | `preview_start`, `preview_delta`, `preview_reset`, `preview_complete` |
| `operation_id` | Captured worker operation identity; Qt-free callers can supply a test identity |
| `candidate_id` | Stable logical request slot assigned before submission, including passage identity for revision |
| `attempt_id` | Monotonic per-candidate request-attempt identity |
| `text` | Answer-only, credential-redacted delta (delta events only) |
| `target` | Safe action/scene or passage label, not entire inputs |
| `result_ref` | Completion's candidate filename/node reference when saved; otherwise preview-result identity |

Start means waiting; delta means provisional answer; reset retires the prior
attempt and starts waiting for the next one; complete marks a fully returned
answer, not acceptance or permission to bypass validation. Final result
binding can occur after parse/save using the same candidate identity.
Failure/cancellation use existing terminal/candidate-failed events and mark the
affected preview nonaccepting; do not invent successful complete events.

Alternative rejected: reusing `k` from `as_completed`, or relabelling by final
position. Neither can associate interleaved deltas, reroll slots and saved IDs.

### Index submitted requests, retain final ordering and retry rules

Extend `many` with an optional indexed-call seam while retaining its existing
zero-argument `fn()` default. Assign candidate slots before `submit`; bind each
callback/attempt tracker to its slot, never a shared mutable “current candidate”.
`chat_many` and multi-draft opt into that seam. Retain `max_parallel`,
completion-order results and shortfall behavior. Carry a private identity/result
association beside the existing results, then emit binding events when outlines/
nodes are saved; do not reorder or change persisted metadata/schema.

At each actual request attempt, including retry after transport/status errors
and text extra-parameter rejection fallback, advance only that candidate's
attempt identity and reset its separator/redactor state. Reuse `_retry` and
existing backoff/token checks; do not introduce new retries. Ignore queued
payloads with an older attempt. Reroll/Add N get a new operation identity and
retain the existing display-slot mapping and captured parent.

### Separate hidden reasoning before emitting any preview bytes

Build the answer-only incremental adapter next to `split_thinking`, retaining
the completed parser unchanged. Do not forward raw `_post` content directly
to the new subscriber. Separate reasoning fields, buffer incomplete tags/
delimiters across chunks, handle explicit and template-opened thinking through
their known boundaries, and expose only waiting/thinking status before answer.
Retain a safe undecidable suffix rather than exposing then retracting reasoning.
Apply the credential change's split-safe redactor before event emission.

The final `chat` return still uses existing `split_thinking`/NoAnswerErr rules;
never change the final answer to match a preview guess. Test split opening/
closing tags, reasoning fields, implicit prefixes with closing tags, no-answer,
mixed content and ordinary nonthinking answers. If the transport supplies no
distinguishable answer boundary, retain waiting status until disambiguation;
do not invent answer tokens or show hidden content to satisfy a timer.
The paused-answer acceptance cases supply a distinguishable actual answer and
must show it before completion, not weaken the assertions to waiting status.

### Route each operation into its owning preview

Thread `preview_events` through these existing functions and all GUI entry/
regeneration paths; local bible forms and deterministic Check do not generate:

| Operation functions | Owning existing controls |
|---|---|
| `planning_operations.generate_outlines` | `outline_generate`, `outline_list`; add read-only raw preview beside `outline_body_edit` |
| `planning_operations.generate_scene_cards` | `scenes_generate`, `scenes_preview`; provisional raw JSON, not card editors |
| `draft_operations.generate_candidates` | `generate`, `_generate_slots`, tray and `preview` |
| `review_operations.update_state_generate` | `update_state`, `continuity_regen`, `continuity_preview`; full and summary-only |
| `review_operations.compress_generate` | `compress`, `continuity_regen`, `continuity_preview` |
| `review_operations.critique_generate` | `critique_scene`, `report_view` |
| `review_operations.revise_generate` | `_advance_revise`, `revise_regen`, `revise_view` |

Keep existing separate raw/diff editors; add a dedicated read-only provisional
pane where necessary rather than overwriting a dirty editor. `MainWindow` stores previews
by `(operation_id, candidate_id, attempt_id)` and routes by captured operation
kind/scene, never current sidebar selection. Candidate selectors show labels
and waiting/streaming/complete/failed states; switching shows accumulated text.
Reading another scene does not retarget the request.

Coalesce adjacent queued deltas if needed for responsiveness, but flush on a
GUI event-loop turn while the request remains blocked. Flush/reset/complete
in order, preserve user reading scroll unless already following the tail,
ignore retired operation/attempt events and clear provisional state on root
switch. Use existing queued worker signals, no direct worker widget access.

### Keep preview, completed parsing and persistence separate

Raw incomplete JSON/tags are labelled provisional and noneditable; Accept/
Choose/Save of generated content stay disabled until the existing full-response
validation allows them. Completed raw-invalid scenes/continuity still use
existing inspection/edit paths; completed valid candidates use existing naming,
warnings and saves. No partial output is written to accepted artifacts or
passage nodes. Existing operation-specific partial-success behavior remains:
only already committed complete candidates survive Stop, not every response
that merely emitted `preview_complete`.

Stop/close and stale guards stay at existing request/chunk/save boundaries.
One terminal signal does not clear `_busy` before thread finish. A visible
failed preview can remain labelled failed for inspection, never accepting.

## Verification

Extend `tests/test_api.py` MockTransport with bounded paused byte streams,
actual attempt retries/fallback, interleaving/indexed batches, chunk-split
reasoning/redaction and no-subscriber request/transcript compatibility.
Extend `tests/test_planning_ops.py`, `tests/test_review_ops.py`,
`tests/test_draft_parity.py` and `tests/test_cancel_and_stale.py` for event
identity, final-byte parity, Stop/stale/error and unchanged accepted artifacts.

Extend `PlanningFake`/`ReviewChatFake` and `FakeProvider` in
`tests/qt_widget_cases.py` to invoke callbacks and block using bounded Events
after first answer text. Existing planning/review fakes returning whole tuples
are insufficient proof. Register `case_stream_planning`,
`case_stream_draft_candidates`, `case_stream_review` and
`case_stream_retry_stop`. `_pump` processes Qt until the right widget contains
the first fragment; assert the completion gate remains closed and `_busy` true
before releasing it in `finally`. Exercise both candidates independently,
including rerolls/additions/regenerations, not just one selected response.
Keep hard timeouts so broken implementations fail, not hang or sleep/race.

## Risks / Trade-offs

- [Implicit reasoning lacks an early unambiguous boundary] → buffer uncertain
  bytes and show Thinking, never leak reasoning; preserve completed semantics.
- [Retry/extra fallback concatenates attempts] → attempt reset at actual
  request boundaries, independent per-candidate tests.
- [Coalescing delays all text until completion] → paused-gate assertions at the
  widget, not just receipt of operation events.
- [Callback/API seam breaks CLI fakes] → optional parameters, update affected
  fakes alongside implementation and retain frozen transcript suites.
- [Large previews stress Qt] → bounded event coalescing, existing concurrency,
  read-only panes and measured responsive Stop; no new job framework.

## Migration Plan

No stored-format migration. Optional subscribers permit incremental adapter
updates without changing CLI callers. Rollback removes preview subscribers,
not completed files. Record commands/results and a separate native Wayland
preview/candidate-switch/Stop/close/focus/scaling walkthrough in implementation
`evidence.md`; unavailable desktop coverage remains PENDING. No new ADR or
blocking product question is introduced.
