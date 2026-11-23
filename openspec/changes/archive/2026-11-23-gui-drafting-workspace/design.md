# Design

## Context

See proposal.md for motivation and `specs/desktop-drafting/spec.md` for behavior.
The branch's `gui_window.MainWindow` already displays sanitized `reader_model`
snapshots, all retained nodes, dirty-preserving refresh and per-scene steering.
Its Generate button is intentionally disabled. `scene_steering` already refuses
unsafe paths and stale tree/card baselines; extend/reuse that protection, not a
second writer hidden in widgets.

`commands.cmd_draft` and `pick_candidates` own the existing workflow:
`build_writer_prompt`, `Api.complete/many`, `clean_continuation`, `Tree.add/save`,
explicit head changes and scene status. `DRAFT_HELP` and `PICK_HELP` define the
parity inventory. The API already streams and has bounded requests, retries,
optional sampler fallback, call logging and calibration. `Api.many` currently
prints and catches every exception; these are extraction/cancellation seams,
not reasons for a new client. `Lore` construction/sync can write the registry.

Repository config describes an older main baseline; this proposal targets the
implemented, unshipped Qt shell on `feat/gui-wayland-shell`, not main.

## Goals / Non-Goals

**Goals:** Finish the draft-loop surface without splitting its basic and advanced
actions between changes; preserve one writing engine, CLI transcripts, prompt
bytes, sampler bodies, branch/history metadata and saved file semantics.

**Non-goals:** No project setup, planning or review operations are extracted here;
no CLI subprocesses, runtime terminal monkeypatching, new provider/network
stack, concurrent project jobs, durable job store or file-format changes.
This is not full GUI completion and does not authorize shipping.

## Decisions

### 1. Extract operations from the existing draft loop

Follow [ADR-0007](../../../docs/adr/0007-shared-writing-operations.md), building on
[ADR-0006](../../../docs/adr/0006-wayland-writing-workspace.md). No new enduring
architecture decision is needed.

Introduce a Qt-independent `draft_operations` boundary as code is moved from
`cmd_draft`, `pick_candidates` and lore mutation helpers. Inputs are captured
plain values: canonical root, scene/card, parent/head, steering, session passage
length, candidate count/IDs, expected source baseline and cancellation token.
Return plain result/error/preview records; emit optional typed progress events.
Keep `Project`, `Tree`, `Lore`, prompt assembly/cleaning and the existing `Api`.
The alternative, calling `cmd_draft` directly, would block on terminal choices;
duplicating generation in Qt would drift prompts and branch semantics.

Operations cover preparation/inspection, generation, acceptance, manual append,
head edit, rewind/jump/delete, scene POV/cast/status, lore changes/import and
prompt dump. Small writes use this same serial dispatch boundary. UI choice
dialogs and text editors run before dispatch, never inside an operation.
`cmd_draft` remains the terminal adapter: it keeps `ask`, `$EDITOR`, paging and
printing, translating the same operations/events into its existing transcript.
Noncancelled CLI behavior and defaults stay unchanged; Qt never calls these
terminal helpers. Optional API cancellation/progress hooks default to existing
CLI behavior. User-correctable errors, including missing credentials/preset,
become sanitized operation outcomes, not worker-ending `SystemExit`.

Generation prepares one exact prompt/params/extra/report for captured inputs.
Respect default `writer.swipes`, explicit N>=1, `max_parallel`, length/token cap,
over-budget refusal, ignored/unsupported sampler warnings, `extra_ok` fallback,
cleaning/leading whitespace/separators, end/trim/absent flags and call metadata.
GUI inspection uses that same preparation: no approximate second prompt builder.

### 2. Candidate batches and explicit head transitions

A generation batch is bound to one scene and its captured parent/head; rerolls
and additions are siblings of that parent, not of the currently viewed node.
Display slots refer to persisted node IDs. For N=1, show stream deltas as a
temporary preview; for N>1, use bounded `Api.many` concurrency and candidate
completion/progress events. Progressive multi-output need not interleave prose;
each completed response becomes viewable with clear candidate numbering.
Completion ordering matches the existing `Api.many` result ordering.

Clean complete responses through the existing rules and save before exposing
them as saved candidates. Streaming text is never a tree node. A failed request,
cancelled response or empty cleaned response creates no node; existing completed
cutoff handling (`finish`, `trimmed`, warnings) remains CLI-compatible, not a
new rule requiring a model's end-of-scene marker.

Accept sets the chosen node as head (thereby choosing its ancestor path),
changes planned -> drafting, and offers Mark done only if the model signalled
end; declining leaves the post-accept status unchanged (normally drafting;
explicitly reopened done scenes retain CLI status semantics). Reroll selected/all replaces only returned
slots and retains originals in the tree; fewer results leave unmatched slots
unchanged with a warning. Add appends returned slots. Keep branches/Discard
preview closes the candidate tray without deleting saved nodes or moving head.
Deletion is a separately labelled Delete leaf action, using `Tree.delete`;
deleting a head leaf moves head to its parent, nonleaf deletion is refused.
There is no automatic acceptance after generation, import, edit or navigation.

If a batch has mixed results, keep successful complete saved candidates and
report failed counts. A later failure/Stop never removes earlier saved branches.
No rollback of earlier completed operations; failure never changes head as a
side effect of generation. Tree and scene saves keep existing ordering and
history behavior, not a promised cross-file transaction.

### 3. One worker, queued events and cooperative shutdown

Use one Qt worker object on one background thread per active operation, owned
by the window/controller. No simultaneous project operations. Only GUI-thread
slots update widgets; queued signals carry operation ID, scene ID, candidate
slot/attempt identity and plain payload. Signals cover started, stream-reset,
text-delta, candidate-completed, warning/progress and one terminal outcome
(success/cancelled/error), followed by settlement. Ignore late payloads whose
operation ID no longer matches; a progress signal cannot silently rebind a view
to another scene. Coalesce deltas if needed without dropping/reordering text.

The GUI owns a thread-safe cancellation token checked by the worker and API,
not a queued Stop slot that cannot run while the worker is busy. Check before
dispatch/request/retry, at stream chunks (including nontext chunks), after
response/cleaning and immediately before each save. Retry waits must be
interruptible. Cancel is a distinct result, never retryable, never swallowed as
an ordinary candidate failure by `many`. Stop schedules no new calls; cancel
pending futures and let active requests observe the token or configured timeout,
then join/settle their bounded internal work before reporting idle.

Reuse configured request timeouts, including the existing connection timeout;
do not promise instantaneous Stop or a total-operation deadline. A blocked read
may wait for its timeout. The status says Stopping/waiting for request; no forced
thread termination, blocking GUI-thread join or new request/retry after Stop.
Stream retries emit reset for the affected attempt so the preview never
concatenates failed-attempt fragments with the successful response.

Check cancellation before a save begins; a save already committed remains
saved. Partial response buffers are discarded on failure/cancel and cannot be
accepted. On completion/error/cancel, settle child requests, quit/clean up the
worker/thread and restore enabled controls exactly once. Keep references until
settlement. Close while working offers **Stop and wait / Keep open**; Stop and
wait keeps processing GUI events and closes only after settlement (and normal
dirty-editor resolution). Keep open does not cancel. Repeated Stop/close is
idempotent. Unexpected operation errors follow the same cleanup path.

### 4. Stale inputs and safe writes

Extend `scene_steering`'s canonical-root, scene-ID, no-symlink and exact baseline
checks to operation targets; do not make `reader_model` a write API. A baseline
captures source bytes/absence and relevant directory membership for config,
preset, selected/all needed scene cards, tree/head, bible/state/summaries, limits,
calibration and relevant lore registry/files used in prompt construction.
Before writing, compare relevant captured inputs and destinations, not just head
or mtime. Imports also capture source bytes and destination absence/content.
If anything changed externally, refuse the write, keep unsaved editor contents,
mark the result stale and offer Reload/retry, never force overwrite.

Generate first saves the captured current steering through the existing safe
adapter, then takes the post-save operation baseline and builds the prompt.
Failed steering save prevents the API call. Steering successfully saved at
dispatch remains saved even if generation later fails. Rebase expected bytes
only after the operation's own verified writes, including candidate saves;
never recapture arbitrary on-disk changes as if they were accepted.

Account for existing hidden writes in `Lore.sync`, `Project.record_calib` and call
logging during extraction: registry/calibration updates require guarded
operation-owned saves and expected-baseline advancement; append-only call
diagnostics are not prompt inputs or manuscript commits. Preserve their CLI
behavior with hooks/staging rather than removing logging/calibration. Failure
diagnostics never turn partial buffers into saved prose. No broader transaction
or cross-process locking is introduced; simultaneous CLI/GUI writers remain
unsupported, and a comparison is not a lock (ADR-0007).

### 5. Desktop controls and state

Extend the existing window, not a second presentation. Retain scene/branch
sidebar, manuscript/notes, splitter, palette, prose size, selection/scroll and
dirty-editor preservation. Add a candidate tray/read pane and compact
Draft/Scene, Branch/Edit, Context and Lore controls, with descriptive labels,
keyboard focus and action availability explanations.

| State | Available controls |
|---|---|
| No writable scene/stale target | Read/refresh/help; disabled writes explain how to recover |
| Some action's prerequisites missing | Disable that action with recovery guidance; missing credentials do not disable manual writing or no-call context inspection |
| Idle, valid scene | Generate (primary), candidate count defaulting to swipes, steering Save/Clear, scene/branch/edit/lore/context actions |
| Generating | Read saved manuscript/nodes/notes and progressive preview, Stop; no conflicting writes, settings changes, import, second operation or project switch |
| Stopping / closing after Stop | Same reading, visible waiting status; no new job; close deferred |
| Settled with candidates | View/select, Accept, Reroll selected/all, Add N, Keep branches/Discard preview, Delete leaf; normal draft actions restored |
| Stale/error | Readable sanitized message and recovery/retry; no acceptance of incomplete or stale buffers; local dirty text retained |

Reading another scene while working is allowed; the job banner/tray names the
original scene and captured parent, and no write targets the new selection.
Draft session length defaults from config and lasts for that open draft session,
not a new persisted setting. POV and cast save existing scene fields. Scene
card is read-only here; full scene-card editing belongs to setup/planning.
Context inspection includes budget parts/ceiling/notes, actual sampler/extra
parameters and injected lore; Exact prompt displays exact bytes and **Save
last_prompt.txt** supplies CLI `cp`'s existing dump, without an API call.

Manual entry uses Save/Cancel and appends source=user with paragraph separator,
advancing head and planned -> drafting. Edit head preserves continuation-leading
whitespace (`keep_lead`), records the old text/time/by=user-edit and shows diff;
empty/unchanged edits are no-ops. Rewind keeps branches; Jump/Use as head chooses
the selected path explicitly, independent of read selection. Full tree shows
parent/children, head/path markers and all metadata/history (including warnings
for end/trim/absent mentions). Manuscript-with-node-markers and configurable
Tail N (default 600) cover CLI `v`/`tail`; help and Leave draft cover `?`/`q`.
Mark done is explicit, exits active drafting controls without closing reading,
and shows update-state as a later continuity step (never auto-runs it).
Done scenes can be explicitly selected for further drafting, as `--scene` can.
Next unfinished chooses the first non-done card, or explains explicit reopening
when all are done. Show resume/head/word-target/sibling status and existing
earlier-scene/summary and preset/sampler warnings rather than silently losing
the CLI's opening diagnostics.

Lore pane lists every discovered JSON/PNG book, on/off, kind, character, aliases,
entry count and POV/present/not-in-scene role. Offer individual/multi toggles,
All on/off, Character + name, aliases and World. Import through desktop picker:
read selected external files, validate with existing card/book parsing (V1/V2/V3
JSON/PNG and World Info), show parse errors/warnings, copy unchanged bytes to
safe `lorebooks/` destinations and run existing discovery/default classification.
No selection means no writes. On name collision offer Replace/Cancel with
explicit destination confirmation and stale checks; preserve existing registry
metadata for that name. Invalid/unreadable inputs leave destination/registry
unchanged; valid empty books remain empty as existing parsing permits.

### 6. Tests beside each seam

Start with a failing offscreen button-flow test in the existing
`tests/qt_widget_cases.py` subprocess harness: generate through the real worker
with an injected fake API, receive controlled deltas, keep head unchanged until
Accept, then reopen and inspect the saved tree. A companion fake midstream
failure/cancel asserts no partial node and recovery. No Qt imports in core tests.

Inject provider factory, event sink, cancellation token and controllable
barriers at request/chunk/save/settlement boundaries. Use deterministic events,
not arbitrary sleeps, to test Stop, timeout, close and stale writes; pump Qt's
event loop to prove a reading action runs while a fake request is blocked.
Exercise actual queued worker signals, not only synchronous mocked button slots.
Keep the existing loader/timer/choice seams for refresh and dialogs; add a file
picker seam returning temporary fixture paths so no modal test interaction.

Before moving each CLI path, capture its fixed-clock prompt/body/tree/scenes/
lore/history and relevant stdout transcript with fake providers and scripted
terminal choices. Compare CLI and GUI operation results byte-for-byte except
explicitly normalized generated timestamps/paths/IDs. Cover continuations,
swipes/rerolls/add, partial batch failure, fallback/warnings, budget refusal,
accept/done, manual/edit, head-leaf/nonleaf delete, cast/lore effects and `cp`.
Add focused headless tests and offscreen cases in the task that introduces each
control. Keep API/network guards, fake credentials and synthetic fixtures;
do not use private projects/presets or skip widget tests without Qt.

The final integration task ensures existing `scripts/check.sh` discovery runs
all additions with its current Qt runtime/offscreen harness; reuse it rather
than add a second check runner. Record real native Wayland acceptance separately,
including worker Stop/close, picker, keyboard/clipboard and available scaling/
theme checks; offscreen success does not establish compositor support.

## Risks / Trade-offs

- [Wide existing draft-loop surface] -> Eight cohesive test-first commits, each
  moving existing behavior and its tests together; no delayed hardening phase.
- [API retries/futures hide cancellation] -> Explicit token propagation,
  interruptible backoff, attempt resets and settlement barrier tests.
- [Multi-file writes can partially succeed] -> Preserve already committed work,
  report what saved, guard each boundary; no false transaction guarantee.
- [External changes after comparison] -> Refuse detected stale writes and keep
  editors; concurrent writers unsupported rather than promising locks.
- [Owner desktop coverage unavailable in automation] -> Keep an honest separate
  Wayland acceptance record; no shipping or whole-GUI completion claim here.

## Migration Plan

No data migration or dependency change. Introduce shared operations behind CLI
parity tests, connect controls incrementally, then run the full offline check
entry point. Existing JSON/Markdown remains readable by CLI and the shell.
Rollback code without transforming project files; generated complete branches
remain ordinary existing-format nodes. Setup/planning then continuity/review/
export remain required for the roadmap's full-parity finish line.

## Open Questions

None blocking build. Optional owner font preference and additional compositor/
monitor combinations affect acceptance recording, not behavior or architecture.
