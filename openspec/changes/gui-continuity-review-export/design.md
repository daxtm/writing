# Design

## Context

See [proposal.md](proposal.md) for motivation and
[desktop-continuity-review](specs/desktop-continuity-review/spec.md) for acceptance.
This is a proposal against the implemented, unshipped `feat/gui-wayland-shell`,
not the older main/reader baseline described in `openspec/config.yaml`.
Drafting and Create-to-scene planning exist; this change implements neither
again and does not establish whole-workspace completion.

The remaining rules live in `commands.py:981–1301`: `cmd_update_state`,
`cmd_compress`, `cmd_critique`, `cmd_check`, `cmd_revise`, `cmd_status`,
`cmd_export`. Reuse these rules and the following existing seams:

| Existing seam | Reuse / gap to fix |
|---|---|
| `Project.scenes/summaries/save_*`, `Tree.chain/text/save` | Scene order, active paths, JSON/newline semantics, node history and continuation separators |
| `parse_sections`, `extract_tagged`, `format_card`, role systems | Exact messages, raw correction and warnings, not a Qt prompt builder |
| `layered_summary`, `check_report`, `words`, `text_hash` | Budget/context notes, exact deterministic reports, freshness and totals |
| `line_diff`, `word_diff`, `keep_lead`, `save_input` | Existing line/word diff content, continuation whitespace, edit-input history |
| `draft_operations` baseline/error/safe-write helpers | Captured bytes, owned-write advancement, cancellation/provider injection |
| `planning_operations.project_overview` | Existing setup overview is intentionally incomplete for `status`; extend rather than add a conflicting overview calculation |
| `gui_window._dispatch`, `draft_worker.OpThread`, cancellation token | Existing one-worker lifecycle; extend event/result routing and dirty-editor handling |
| `reader_model` snapshots, Notes tab, metadata history | Existing summaries/arc/report reading; add safe state/input history viewing, not a mutation service |

`MainWindow` already receives queued events with operation IDs. Notes are
read-only; `_resolve_dirty` covers steering/planning and close currently checks
steering. Review needs those **existing** dirty/close/settlement paths extended:
do not bolt on a second job manager or independent close protocol. Its generic
“nothing was saved” Stop message is insufficient after accepted revisions.

## Goals / Non-Goals

**Goals:** Finish the selected M3 GUI surface using small shared operations and
explicit author decisions; freeze CLI behavior before extraction; make
report/diff/history inspection and all editing possible without a terminal.

**Non-goals:** No new dependencies, file schemas, persisted sessions, background
queues, transaction/lock service, branch-per-revision model, automatic summary
refresh, history-restore engine, changes to CLI choices or creative prompts.
No implementation or shipping in this planning commit.

## Decisions

### 1. Extract the remaining orchestration, not another writing engine

Follow [ADR-0007](../../../docs/adr/0007-shared-writing-operations.md) and
[ADR-0006](../../../docs/adr/0006-wayland-writing-workspace.md).
No new enduring architecture/data-format choice or ADR is needed. Put the
remaining Qt-independent actions in `longform_core.review_operations`, reusing
current guards/provider/error helpers rather than reimplementing them.
Extend existing overview/lore read helpers where needed. Business operations
must not import Qt, call `ask/page/edit_saved/edit_text`, start subprocesses or
manipulate widgets; CLI adapters retain those presentation choices.

Each action takes canonical root, scene/range/choice, plain edited text,
opaque expected baseline and optional provider factory/token/event sink.
It returns a plain prepared preview/result with warnings, targets and a
baseline. Separate preparation/generation, edit-input saving and acceptance.
No worker waits for the author's next choice. Preview sessions are in-memory
records, not files; reopening reads saved reports/continuity/history but cannot
accept an old generation without preparing against current sources.

| Operation family | Shared boundary |
|---|---|
| Update state | Resolve default/explicit scene and warnings; prepare exact messages; generate/parse raw response; save raw/section input; accept validated sections |
| Compress | Resolve/validate inclusive range and replacement set; generate exact summary; save edited input; accept arc |
| Critique/check | Generate/compute full report preview; save generated report; read/edit/save existing report |
| Revise | Begin session with captured chain/notes; generate one passage; save edited proposal; accept/skip/finish and return advanced session |
| Status/export | Extend read-only full overview; compose exact manuscript plus count; guarded write to explicit selected destination |

The CLI remains an adapter with the same default scene, prompts, warning
order, editor invocation, paging, request parameters and save order. CLI
critique/check still save immediately after their explicit command succeeds;
GUI previews instead require Save. CLI compress/revise `e` still means
edit-then-accept; GUI Save edit means preserve input/return to preview and
requires Accept separately. This presentation difference does not change
shared normalization/persistence or CLI transcripts. Characterization fixtures
must cover these asymmetries rather than silently simplifying the CLI.
Direct `cmd_*` calls or stdin automation would block and are rejected; a
Qt-only prompt/report implementation would duplicate the rules and is rejected.

### 2. Extend existing panes and the single worker

Add Continuity (Update state / Summary only / Compress range), Review
(Critique / Check selected / Check all, saved report selector and editor),
Revision (passage/progress/original/proposed/diff/actions), Status and Export
controls in the current window. Keep the existing read-only Notes entries and
refresh them after explicit writes. Scope selectors show scene IDs/titles;
review/report selection is explicit and does not retarget an active preview
when the reader navigates to another scene.

Use `_dispatch`/`OpThread` for prepare/generate/check and all mutation/export
actions. Cheap cached status/snapshot rendering stays on the GUI thread;
expensive fresh overview reads use that same worker when idle. All widget
changes, dialogs and author decisions happen on the GUI thread via queued
signals. Events carry operation ID and target identity; ignore late/foreign
events. Reading saved text/history remains available during work; project
switch, conflicting editing commits, other generation and export are disabled.
Prevent actions from retargeting work if selection changes while it runs.

One operation at a time includes the interval until the underlying thread
finishes: do not clear the busy gate early merely because a terminal-result
signal arrived. Reuse/fix current settlement handling and retain one terminal
outcome. Stop checks the token before requests, at available chunk callbacks,
after responses and before the next commit. `Api.chat` is currently a
nonstreaming request; show indeterminate progress and respect its configured
timeouts instead of promising immediate Stop or inventing a streaming engine.
Existing retries/calibration/logging remain in `Api`.

Close offers Keep open or Stop and wait, remains responsive while waiting,
then resolves **all** dirty editors. No forced thread termination. Failure,
Stop or stale refusal discards provisional output, preserves previously saved
inputs/reports/accepted revisions and restores controls. Track saved revision
count/targets so the result never falsely says “nothing saved” after earlier
acceptance. Stopping between passage decisions ends the session without
undoing accepted work.

### 3. Continuity and compression preserve exact acceptance semantics

Update-state default is first done/not-state_updated scene; explicit scenes
with text are allowed even if not done, with the existing warning. Show later
state_updated IDs before a full-state call and require Continue anyway;
Summary only avoids that override. Retain the token-ceiling warning without
turning it into a new hard gate. Prepare the exact existing section instructions,
state-before text and full active scene text.

Keep raw response/finish reason when parsing fails. Required nonempty sections
are `DETAILED SUMMARY`, `BRIEF SUMMARY`, and, only for full mode, `UPDATED STATE`.
Built-in raw and section editors use the existing parser. Show both summaries,
full proposed state and the `line_diff(state, proposed, "state.md", "updated")`.
Editing a preview never silently accepts it. Successful Accept performs the
existing backup → state → summary → scenes save sequence; summary-only does
not modify state/history/flags (the CLI may reserialize unchanged scenes).

Compression validates scene-ID membership and list order, inclusive lo/hi,
and presence of **every** per-scene summary before requesting. A one-scene
range is valid; no new done/current-hash requirement is introduced. Overlap is
inclusive, including shared endpoints. As in CLI, ignore arcs with endpoints
absent from current scenes. Replace removes **whole** intersecting arcs, even
if they extend beyond the selected range; no splitting or stitching.
Show that exact deletion set and bind Replace consent to its baseline before
generation/acceptance. No-overlap needs no Replace. A missing `<summary>` tag
is a warning, not invented parsing failure. Preview/edit/regenerate/quit
changes no arcs; Accept filters overlaps then appends the new record.

### 4. Reports and revision reuse existing formats and diffs

Critique uses existing layered prior-summary budget and warnings, state/bible/
card/text, banned phrases and exact critic instructions. Missing text is an
error; no writer-preset requirement. Generate returns a preview; Save writes
the CLI heading/body and backs up an existing report first. Built-in editing
of saved critique text writes the Markdown verbatim and uses the same `_prev_`
backup convention. This replaces the CLI's instruction to edit the report
externally without adding a new review-note format.

Check captures selected/all active paths in scene order and calls existing
`check_report`. Do not instantiate `Api` or demand credentials. Keep banned
phrase filtering, ngram settings, node/snippet locations, tie order and `(none)`
messages exactly. Run previews; Save overwrites the scoped existing path with
the full report. A saved report can be edited as plain Markdown; check saves
have no new history/backup scheme. The UI always labels scene vs all scope.

Revision begins with the captured chain, scene card, bible and saved
`critiques/<scene>.md` followed by `checks/<scene>.md`, stripped and joined as
in CLI. `checks/all.md` is never substituted. With neither scene note file,
show the existing prerequisite message and do not call. Retain the chain list
for this session; accepted changes update existing nodes **in place**, including
shared ancestor text on other branches, as CLI does. Make this visible; do not
invent new candidate branches or move head/counter/status.

Generate one passage using the exact editor message and output cap
`max(editor.max_tokens, int(words(original) * 2))`. The preceding tail is the
last 900 characters of `Tree.text(previous_node)` using earlier accepted edits.
NO CHANGES (case-insensitive prefix) or identical trimmed output advances with
no save. Missing tags and length finish show the existing warnings. Display
original, full proposed text, word counts and `word_diff`; reuse its content
with color disabled/translated for Qt, not a second diff algorithm. The state
diff similarly keeps the existing unified-line labels/content.

Accept requires nonempty text, uses `keep_lead` for `sep == ""`, appends
`{time, text: old_text, by: "revise"}` and saves the tree, then advances the
session baseline. Skip advances without writing. Edit saves input and returns
to diff; Regenerate repeats this passage's captured prompt; Quit retains prior
accepted edits and stops before the remaining passages. The GUI reports the
accepted count and stale-summary recovery action whenever appropriate; preserve
the CLI's existing quit-vs-normal-completion transcript, including its existing
normal-completion-only stale warning. Never automatically regenerate summaries.

### 5. Formats and history are existing files, not new schemas

| File | Preserved contract |
|---|---|
| `summaries.json` scenes | `{detailed, brief, updated, text_hash}` keyed by scene ID; retain unrelated scenes/arcs |
| `summaries.json` arcs | Ordered `{from, to, text, updated}` records; compression removes intersecting records then appends |
| `state.md` / `state_history/before_<scene>_<stamp>.md` | Full accepted state stripped plus newline; prior state copied with existing copy semantics |
| `scenes.json` | Full-update acceptance sets selected state_updated; summary-only keeps flags; preserve unrelated fields/order |
| `inputs/state_raw_<scene>.md`, `state_edit_<scene>.md`, `arc_<from>_<to>.md`, `revise_<scene>_<node>.md` | `save_input` latest plus `inputs/history/<kind>_<stamp>.md`; saved even for invalid edits |
| `critiques/<scene>.md` | `# Critique <scene> (<now>)\n\n<body>\n`; overwrite backup `<scene>_prev_<stamp>.md` |
| `checks/<scene-or-all>.md` | Exact `check_report` output and final newline; no automatic check-history directory |
| `trees/<scene>.json` | Existing nodes and history only; retain separators, metadata, branches, head and counter |
| Chosen export destination | Existing title/chapter/scene separators and `Tree.text`, exactly one joining/final newline contract |

Use current `write_json/write_text`, clocks and naming; do not add schema
versions or migrate existing files. “Arc history” means existing saved arc
records and edited input versions: **the CLI has no automatic old-arc snapshot
store**, so do not invent one or claim replaced unedited arcs are recoverable.
Expose safe read-only history lists/full-text viewing for state backups, matching
input versions, critique prev files and node revision history; no restore/delete
feature. Continue using the snapshot reader's bounded/sanitized file access
and path rules, with errors for malformed/unreadable records.

### 6. Status is read-only; export is explicitly destination-bound

Extend the existing setup overview with the complete `cmd_status` facts,
using `Project.ceiling/writer_ceiling`, the configured writer preset and
active `Tree.text`/`words`/`text_hash`. Expose public role/model/ceiling/preset
facts, never raw config or credentials. Missing preset is the CLI missing-path
fact; malformed/unreadable preset/tree means a visible error/partial state,
not fabricated zero/complete totals.

`Lore(p, scenes)` currently calls `sync`, which can create directories, print
discovery notices and save a registry. Do not call that mutating constructor
from GUI status/refresh. Reuse/extract its active-book calculation as a
read-only helper: registered-on entries whose files exist; undiscovered books
default off. CLI retains legacy discovery notices/registration at its original
point using the existing guarded lore operation seam before presenting shared
facts. Test discovery separately from facts so ordinary status parity and
byte-identical legacy transcript are both preserved. No automatic GUI discovery
write is needed to show the same active-book list.

Export uses a Save-file dialog, suggested `root/manuscript.md`; Cancel is a
no-op. Compose once using CLI's exact loop, **including** its existing chapter
transition and same-chapter separator condition; do not replace it with a
“cleaner” renderer. Only scene-list active heads count, empty scenes are skipped,
retained/orphan trees and inactive branches are excluded. Display final resolved
path and exact `words` total after a successful write.

The picker explicitly authorizes a destination outside the project; it is not
permission to write arbitrary paths from scene IDs/report names. Capture
destination bytes/absence before overwrite confirmation. Confirm the full
resolved path if present and verify it again before writing. Reject directories,
symlink final targets, aliases of project source/report/history files, and
unwritable/invalid destinations; `manuscript.md` remains an allowed output.
Do not create missing parent directories implicitly from a cancelled picker.
Source/destination changes require a fresh export/confirmation. CLI preserves
its current `--out` resolution and overwrite behavior; GUI adds the explicit
confirmation, not a CLI prompt.

### 7. Dirty/stale checks extend the current guard, not concurrency guarantees

Capture exact bytes/absence of all inputs that influence a pending result and
all destinations before work. At minimum:

| Work | Captured sources / pending destinations |
|---|---|
| Update state | project/config, scenes/order/flags, selected tree/head, bible, summaries, state, limits/calibration; state/summary/scenes/input targets |
| Compress | project/config, scene order, summaries including replacement set; summaries/input target |
| Critique | project/config, scenes, tree/head, bible/state/summaries, limits/calibration; selected critique target |
| Check | project/config and ngrams/banned phrases, scenes, selected/all trees including absent ones; scoped report target |
| Revise | project/config, scenes, selected tree, bible, both scene-note paths including absence; tree/input targets |
| Export | project/config, ordered scenes and every referenced tree including absence; chosen destination |

Validate the whole applicable baseline before backup/write, and use existing
safe-target guards for every source/target/history directory: IDs cannot
traverse paths and project symlink escapes cannot bypass the guard. Include
edit-input destinations in their own baseline so saving input cannot silently
overwrite a different session's input. Refuse stale writes with reload/retry;
retain local text and never “refresh baseline then save” without regenerating/
re-preparing against the changed sources. Replace confirmations expire with
their baseline. API-owned calibration/log changes and each accepted revision/
report/input save advance only known owned bytes, not an entire recapture that
would mask external edits. A raw-input save may still preserve the author's
correction while its parent proposal remains stale/unacceptable.

Extend the existing dirty registry and transition resolver to raw/section/arc,
report and revision editors alongside steering/planning. Save on a preview
saves edit-input history, never continuity/arc/node acceptance. Save on an
existing report editor commits that report. Discard restores its baseline;
Cancel/failed/stale Save keeps the scene/project/window open. Confirm loss of
unaccepted previews before replacing them; accepted work is never rolled back.
A fresh external report must not overwrite local edited text on timer refresh.
Preserve selection, tab, scroll, cursor and reading position across updates.
Run Revise/Export only from saved sources; if relevant notes/prose/settings are
dirty, offer Save/Discard/Cancel first, then require the explicit action again
after successful Save rather than silently launching work.

Check cancellation/staleness immediately before each logical commit group.
Do not interrupt an already-started tiny backup/state/summary/scenes commit
between its own writes; settle it and report what completed before another
request. Existing multi-file saves are not transactions: I/O failures can leave
completed writes/backups. Report accurate affected paths and retain recoverable
history; do not promise rollback or solve concurrent CLI/GUI writers here.

## Risks / Trade-offs

- [Extraction changes terminal conversations] → Freeze pre-extraction fixed-clock
  files/messages/diffs/transcripts, including editor-implies-accept and early Quit.
- [One task spans several controls] → Follow eight dependency-ordered commits,
  with local red-to-green unit/Qt cases beside each operation family.
- [Stop waits for chat timeout and earlier saves survive] → Show stopping and
  saved-count messages, keep reading responsive and never claim a rollback.
- [Stale checks are not cross-process atomic locking] → Refuse changed bytes
  before writes, retain the existing unsupported-concurrent-writer limitation.
- [Manual report edits invalidate prior revision inputs] → Bind both notes
  paths to the revision baseline and require a new session after changed notes.
- [Offscreen success is mistaken for native desktop completion] → Keep real
  Wayland evidence separate and PENDING until observed on the owner's desktop.

## Verification and acceptance

Start with a red offscreen button journey on temporary synthetic completed
scenes: full/summary-only update, compress, critique/check, edit report, revise
Accept then Skip, Status, picker Export, reopen and compare CLI output. Add
pre-extraction CLI characterization and headless operation tests at fixed clocks;
normalize only temp roots/timestamps, not content/whitespace/order/messages.
Use fakes/MockTransport and existing credential/network guards; forbid terminal
helpers in desktop tests rather than monkeypatch them as an implementation.

Each feature commit adds focused offscreen cases for its controls and headless
parity/error cases. Cover malformed sections/tags, earlier-scene confirmation,
range/overlap boundaries, no-change/truncation/continuation history, scene/all
scope, stale sources/destinations, dirty transitions, Stop/close/failure and
late-result isolation. Exercise status read-only even with undiscovered lore.
Existing `tests/test_qt_cases.py` must run every new case in its offscreen
subprocess; missing Qt or failure is nonzero, never a skip. Keep the installed
GUI runtime and all existing tests/guards in `./scripts/check.sh`.

Real Wayland acceptance is **PENDING — not performed by this proposal**.
Implementation records compositor/runtime/platform, full completed-scene-to-export
demo, pickers/overwrite, keyboard/clipboard/focus, resize/100%/200% and available
fractional/mixed scaling, light/dark, Stop/close in `evidence.md`, with unavailable
combinations explicit. Offscreen output cannot fill that evidence.
After M3, audit **every row** of the roadmap command/action parity matrix across
M1–M3 (Create → export and all draft actions), mapping controls/tests/evidence
and naming any gap before claiming completion. This is acceptance within the
existing roadmap, not a new milestone or authorization to ship.

## Migration Plan

No migration: existing projects and CLI entry points stay valid. Land the red
journey, then incremental shared extraction plus controls/parity tests, then
check-entry integration and acceptance evidence. Rollback the implementation
commits to remove controls; existing-format saved work remains readable.
Do not auto-restore histories on rollback. This planning change only selects/
proposes M3; implementation tasks remain unchecked. No blocking choices remain.
