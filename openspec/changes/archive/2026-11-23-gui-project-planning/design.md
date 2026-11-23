# Design

## Context

See [proposal.md](proposal.md) for motivation and
[the capability delta](specs/desktop-project-planning/spec.md) for acceptance.
This targets the implemented, unshipped `feat/gui-wayland-shell`, not the older
main/reader baseline described in `openspec/config.yaml`. `gui_window.MainWindow`
already has safe reading, draft operations, injectable provider/picker/choices,
dirty steering, and `_dispatch` over `draft_worker.OpThread`. Planning must also
work when `reader_model.load_snapshot` cannot yet produce a valid project.

Relevant existing seams:

| Source | Behavior to retain/extract |
|---|---|
| `commands.cmd_init` | Default five files, seven directories, create missing only, master-export import |
| `Project.preset_path/preset` | Configured preset location, four required master keys, in-memory overrides |
| `commands.cmd_limits` | `/plan`, distinct configured model lookups, 404/not-found, limit extraction/output |
| `BIBLE_QUESTIONS`, `bible_form`, `compose_section`, `split_bible`, `join_bible` | Fixed questions, character forms, comments/blank answers, existing Markdown normalization |
| `cmd_bible`, `utils.save_input` | Whole-bible session backup, saved answer forms and input history, budget warning |
| `cmd_outline` | Exact planner messages, notes filtering, candidate naming/notes comment, selection/history |
| `cmd_scenes`, `extract_json_array`, `Project.save_scenes` | Tagged/fenced JSON parsing, defaults/IDs, preview, force protection and backup |
| `reader_model`, `scene_steering`, `draft_operations` | Canonical root, safe reads, exact-byte stale checks and guarded writes |
| `Api` | Credential resolution, GET/chat/many, retries/timeouts, reasoning separation, warnings, calibration/logging |

## Goals / Non-Goals

**Goals:** Extend this window incrementally from no project through saved scene
cards, using shared operations and the same files that existing drafting reads.
Preserve valid CLI behavior with pre-extraction characterization tests.

**Non-goals:** No database, new schemas/provider discovery service/dependencies,
standalone launcher, second engine, all-command rewrite or implicit pipeline.
No migration of credentials or unrelated continuity/review/export extraction.

## Decisions

### 1. Extend the current window and shared operation boundary

Follow [ADR-0006](../../../docs/adr/0006-wayland-writing-workspace.md) and
[ADR-0007](../../../docs/adr/0007-shared-writing-operations.md); no new enduring
decision or ADR is required. Add Qt-independent `planning_operations` by moving
only the work needed for each control out of the five `cmd_*` functions.
Reuse `Project`, templates/questions, parsing/composition, `save_input`, `Api`
and existing error/baseline utilities rather than duplicate rules in widgets.
Extract a small shared guard helper only if necessary for both operation modules;
do not turn `reader_model` into a mutation service or refactor all drafting.

Operations accept plain captured inputs, opaque expected baselines, optional
provider factory/token/event sink; return sanitized plain view/result/error
records. The CLI keeps questions, printing, paging and `$EDITOR` as an adapter,
including original defaults and successful/known-error transcripts. GUI calls
never reach `ask`, `page`, `edit_text`, subprocess commands or runtime terminal
monkeypatches. Operations separate prepare/generate, preview, and explicit commit:
workers never wait for an author decision. Direct `cmd_*` calls would block;
a Qt-only implementation would diverge. GUI-only manual edits use the same
composition/normalization/save boundary, without adding CLI prompts.

### 2. Create/Open and project-independent navigation

Retain `gui DIR` and strict native Wayland startup; no CLI signature change.
Always show Create/Open on the top bar and a setup pane, including for a missing
directory, missing/invalid config or zero scenes. A missing project opens in
setup state, not a fatal `Project` constructor. Create opens a directory dialog
with a proposed path from DIR and desktop new-folder selection; explicit Create
initializes that canonical location. Open selects an existing directory and
reads it without initializing, repairing or making calls. Cancel leaves the
current root and disk unchanged. Never initialize simply because a timer refreshed.

Initialization reuses `cmd_init`'s payloads exactly:
`project.json`, `bible.md`, `state.md`, `scenes.json`, `summaries.json`; directories
`trees`, `outlines`, `critiques`, `checks`, `state_history`, `lorebooks`,
`bible_history`. Do not eagerly create `outline.md`, inputs, credentials or limits.
Existing files are never replaced, even if malformed; name collisions with
directories, symlinks or unreadable targets are errors, not permission to reset.
Report created/skipped files and partial completion accurately, as initialization
is not a transaction. Repeating Create fills missing paths without changing others.

Preset import has a separate file picker, available during Create and afterward.
Use the existing JSON/master validation (`instruct`, `context`, `sysprompt`,
`preset`) and copy original bytes to `writer_preset.json`, as `init --preset`
does. Additional structural checks report malformed objects needed by the writer,
not a new preset format. Existing destination means warning/no overwrite, with
no Replace button; configure an existing preset path in Settings if appropriate.
Picker cancel/invalid source never changes the preset. `Project.preset` remains
the source of override semantics and readiness checks.

Switching projects resolves all dirty editors through Save/Discard/Cancel first;
failed/stale Save prevents switching. While a worker is active, Create/Open are
disabled. A completed switch clears old cache/baselines/candidate selections,
binds the new root and reloads settings/session/scene views. Invalid Open reports
the problem without destroying the currently usable project; initial invalid
DIR remains a readable setup/error state, with no write enabled against bad data.

### 3. Settings: explicit allowlist and no secret view model

Settings loads merged defaults for supported controls but commits a patch over
the original JSON object, preserving unknown fields and unrelated values.
Do not show a raw configuration editor or pass the configuration/Api headers to
widgets. Supported fields are:

- General: `title`, `target_words`, `api_base`, `api_key_env`,
  `max_context_fallback`, `context_safety_margin`, `prompt_budget`,
  `chars_per_token_default`, `max_parallel`, `request_timeout_s`.
- The existing planner/writer/summarizer/critic/editor model IDs; for chat roles,
  `SAMPLING_KEYS` and `thinking`, `thinking_budget`, plus
  `chat_template_kwargs`'s existing thinking/enable_thinking/thinking_budget keys.
  Preserve other existing kwargs without displaying/editing them.
- Writer: `preset`, `swipes`, `passage_words`, `user_name`,
  `absent_character_lore` (`reference` or `exclude`), `lore_match_whole_words`.
- `budget_tokens`'s seven fields, `summary`'s four fields, `banned_phrases`,
  and `ngram.n/min_count/top`.
- Writer preset overrides actually consumed by `writer_sampling`/ceiling:
  `temp`, `top_p`, `top_k`, `min_p`, `rep_pen`, `freq_pen`, `presence_pen`,
  `genamt`, `max_length`, `dry_multiplier`, `dry_base`, `dry_allowed_length`,
  `dry_sequence_breakers`, `dry_penalty_last_n`. Preserve unsupported existing
  override keys without offering new inert controls; show existing ignored-sampler
  warnings through the shared preparation/report, not raw config.

Each optional control supports unset (remove override/use default); do not
materialize unrelated defaults on save. Validation is local domain validation,
not a claim to know every provider model's limits: strings for textual fields,
nonblank model IDs/preset/environment name, valid HTTP(S) base URL without
userinfo/query/fragment, finite numbers only, booleans not accepted as integers.
Positive integers for target/context/prompt/parallel/swipes/passage/max_tokens/
genamt/max_length/ngram values; positive timeout/ratio; nonnegative integers for
section budgets, summary counts/word lengths, min_tokens, thinking_budget, top_k
and DRY lengths.
Safety margin is `[0,1)`; probability fields `[0,1]`; temperatures and DRY
multiplier are nonnegative; repetition penalty and DRY base are positive;
presence/frequency penalties are finite; seed is an integer; stop is text or a
list of strings; banned phrases/sequence breakers are lists of strings (serialize
breakers in the existing accepted form). Refuse `min_tokens > max_tokens`.
Explain field errors and leave disk/dirty form unchanged. Model availability
comes from explicit limits, not a call on every keystroke.

Show `api_key_env`'s name and environment availability separately from effective
credential availability (the existing CLI may have an inline `api_key`).
Resolve availability in core using the same precedence as `Api`, returning only
booleans. Never return, render, enter, copy, log, persist a new key or expose
Authorization headers in a GUI outcome. Preserve an existing inline `api_key`
opaquely on nonsecret settings saves for CLI compatibility; do not migrate,
erase or echo it. New projects retain the existing empty default field.
Validate environment names with Api's name regex. Errors, provider bodies and
URLs are sanitized before reaching labels/dialogs; use sentinel-secret tests
for both inline/environment sources, including a provider error echoing a key.

Fetch limits is an explicit worker action; it does not run on Create, Open,
Save settings or tab changes. Save pending settings explicitly first (or cancel
Fetch); then reuse `/plan` and one `/models/<id>` lookup per distinct role model.
Show fetched time, plan context/concurrency, each role/model's found/context/
max-completion/availability, raw model metadata only after sanitization, and
not-found/unavailable/error messages. Preserve `limits.json`'s existing shape.
Full fetch success commits it; transport/plan/unexpected model failure or Stop
keeps the previous file; a model 404 remains a successful `found:false` result.
Missing credentials disable calls, not local planning/editor controls.
No implicit generation, billing probe, limits fetch or next command.

### 4. Bible forms are not a lossy reverse parser

Bible pane lists sections in `split_bible` order, displays current text, fixed
questions and multiline answers using the existing form text as the canonical
answer representation. An editable multiline form is sufficient; do not invent
an inverse parser from arbitrary Markdown to answers. Load
`inputs/bible_answers_<slug>.md` if present, otherwise `bible_form`, including
lore-derived character names, blank extra character, Other characters and Other
notes. Reuse all question wording, character field names and comment/blank rules.

Begin answering explicitly starts a session and copies an existing bible into
`bible_history/bible_<stamp>.md` once, matching `cmd_bible`; simply viewing is
read-only. Save answers persists exact form and `inputs/history` using
`save_input`, then previews `compose_section` without changing `bible.md`.
Accept replaces only the chosen section in the captured preamble/ordered sections
through `join_bible`. Edit answers returns to the form; Skip/Leave correspond
to skip/quit: previously saved answers and accepted sections remain, but the
unaccepted preview is not committed. Dirty unsaved forms still require resolution.

Existing nonplaceholder text is never converted to a blank form automatically:
show it beside preview and require explicit Accept to replace it. Offer direct
section-text Edit/Save/Cancel for freeform text and custom headings, backed up
before change; never relabel headings, drop custom sections/preamble or invent
answers. Retain existing split/join whitespace normalization on a successful
save, not a promise of byte-identical whitespace in untouched sections.
History viewer reads safe existing bible snapshots/answer-history files; no
restore protocol is needed. Show existing estimated writer-token budget warning.
Malformed/no-section bibles are readable with an error, not silently reset.
Lore discovery's possible registry writes must use the existing guarded
operation seam, not happen merely when the section list paints.

### 5. Outline candidates bind to captured inputs

Outline pane contains raw saved notes with multiline editing, N>=1, Generate,
Reroll same notes, Edit notes and reroll, candidate list/full viewer, working
body editor, Choose/Save outline and Cancel/Leave. Saving notes uses
`inputs/outline_notes.md` and `inputs/history`; filter leading-`#` lines only
when constructing the exact `cmd_outline` messages. No prerequisite writer
preset for planner calls. Missing/empty bible blocks generation; placeholders
do not impose a new required questionnaire. Bible token warnings belong to the
existing Bible budget display, not a new outline prompt/generation policy.

Use `Api.chat_many("planner", ...)`, preserving `max_parallel`, completion
ordering, reasoning/finish warnings, `extract_tagged` fallback, candidate file
names and optional `<!-- notes: ... -->` prefix. Append reroll candidates, never
delete prior files or choose one automatically. List saved candidates after
reopen; older candidates are inspectable, but accepting a freshly generated
result requires its original source baseline. After reopen, choosing a saved
candidate is a new explicit operation bound to the current inputs and shows
that it came from history, not a claim that it reflects the current bible.

Choose strips only the existing leading notes comment, copies prior `outline.md`
to `outlines/outline_prev_<stamp>.md` if present and saves the chosen body with
existing newline semantics. Editing works on a local body; Save commits through
the same backed-up boundary, leaving the original candidate unchanged. No
automatic scene generation. Partial-batch failures show warnings and keep complete
saved results; no-result failure/Stop never replaces `outline.md`.

### 6. Scene generation and editing share normalization, not tree mutation

Planning Scenes pane displays existing cards, Generate/Regenerate, full
card/list preview, editable fields, validation errors, total/project target
words, Accept/Replace and Cancel/Leave. Generation requires a nonempty saved
outline and valid planner configuration/credentials, not a selected scene.
Use exact `cmd_scenes` messages and existing tagged/fenced JSON extraction.
Invalid arrays retain `outlines/scenes_raw_<stamp>.txt` and the raw viewer with
Regenerate/Cancel; they cannot overwrite `scenes.json`.

Extract normalization from the acceptance block: defaults, strings/lists,
numeric word conversion, ordered IDs (`s01`, three digits beyond 99),
`notes:""`, `status:"planned"`, `state_updated:false`, existing JSON serialization.
Keep valid CLI fixtures (including omitted fields/defaults) byte-identical.
Share validation for malformed shapes/conversions so bad output becomes a
recoverable error instead of `ValueError` or a character-by-character list.
Do not add new creative/POV rules or require word totals to match exactly.
Candidate editors require a nonempty list of object cards; text fields must
be strings, cast/beats lists of strings, chapter a positive integer,
target_words a nonnegative integer; normalize integer-form numeric strings
as the old CLI does. Missing generated fields use existing defaults; warn on
zero words, missing descriptive values or total mismatch, but do not invent
content. Invalid types, negative/nonintegral counts and unsafe IDs cannot save.
New malformed-type errors are an intentional safety fix in the shared seam;
existing parse-failure messages and valid transcripts remain unchanged.

Before generating, if any existing card is not planned or any `trees/*.json`
exists, require a GUI force confirmation equivalent to `--force`, naming
`scenes.json` and explaining trees are retained. Before accepting any replacement
of a nonempty scene list, confirm replacement and current backup destination;
bind confirmation to captured scene bytes/tree membership, and never treat it
as consent to replace later changed data. On acceptance, copy previous
`scenes.json` to `outlines/scenes_prev_<stamp>.json` as existing behavior does,
then save. Generation and preview alone never replace scenes.

Existing-card Edit is distinct from regeneration: update chapter/title/pov/
setting/characters/goal/conflict/outcome/beats/notes/target_words in place,
preserving IDs, order, status, state_updated and unknown fields. Use the same
previous-scenes backup on changed saves. No ID editing/reordering, automatic
status reset, tree deletion or retargeting. Unchanged Save is a no-op.
The existing draft POV/cast controls remain supported; both read the current
saved cards after commits. Refresh stale selections/trays/session prerequisites
without dropping dirty steering or manual prose. Retained trees stay readable,
including trees no longer represented by regenerated cards.

### 7. One worker, consistent lifecycle and guarded persistence

Reuse `_dispatch`/`OpThread`, cancellation token, operation IDs and queued events
for all planning work, including small writes. Add planning result/event handlers
instead of a second worker/job system. Only GUI-thread slots touch widgets.
Reading remains usable; all conflicting saves/imports/draft acceptance/project
switching are disabled during an operation, with a visible reason. Recompute
availability after success/error/Stop; no missing-scene gate on setup controls.

`Api.get/chat/chat_many` currently lack the cancellation/event hooks already
available on drafting `complete/many`. Add optional backward-compatible
token/event hooks there, preserving defaults and noncancelled CLI output.
Check token before requests/retries, at streamed chunks, after responses and
before saves; interrupt retry backoff. A blocked GET/read may wait for the
configured timeout. Settle internal bounded `many` futures before idle; do not
kill threads, start new retries after Stop or accept partial streamed responses.
Keep already committed candidates/answers/backups; report what actually saved,
not the draft handler's universal "nothing was saved" message. Close offers
Stop and wait / Keep open; wait without blocking the UI, then resolve all dirty
editors. Project/tab navigation cannot commit a preview.

Capture exact bytes/absence and relevant directory membership at edit/generation
start, carry them through preview/accept, and compare immediately before every
write/backup. Include settings, bible/answers, notes, outline/candidate source,
scene list, relevant lore files/registry, limits/calibration when consumed, and
tree membership for force protection; capture import source bytes too.
Rebase only verified operation-owned changes. `Api.chat` calibration and call
logging remain compatible; guard/advance calibration writes, keep append-only
call diagnostics separate from prompt baselines. Sanitize worker errors before
emission, including terminal-origin exceptions.

Reuse canonical-root/no-symlink safety for source reads and every destination,
backup directory, temporary file and parent below root; reject relative config
preset paths escaping root. Explicitly selected external presets may be read only as import
sources; an existing external configured preset may be read via a validated
read-only path for compatibility, never mutated by Settings/import. Compare its
bytes if consumed. Check unsafe paths before invoking `write_text` (which uses a
`.tmp` sibling); refuse damaged destinations rather than following links.
Detected stale/unsafe changes preserve disk and dirty editors/previews, show
Reload/Keep editing guidance and require reload/new generation or explicit
historical-candidate selection, never a force-stale overwrite.

## Tests and Acceptance

First add a red offscreen user journey to `tests/qt_widget_cases.py`: missing DIR,
Create through injected directory/preset pickers, Save settings, Fetch limits
with fake Api, save bible answers, Generate two outlines/reroll/select, generate/
edit/accept scenes, select a scene in existing Draft and reopen. Assert no call
before explicit request and fail if terminal/editor/subprocess helpers run.
Use real worker/queued signals, existing network guards and synthetic presets.

Before each extraction, freeze that CLI path's messages/provider bodies,
stdout/stderr, created files/inputs/history/backups under fixed clocks and
deterministic provider responses; compare the GUI operations' corresponding
outputs byte-for-byte. Normalize only fixture roots/timestamps when unavoidable,
not prose/prompt/samplers. GUI-only edits have direct file/history assertions.
Add headless validation/safe-path/secret/stale tests next to each feature.

Use barriers/events, not timing sleeps, to prove GUI reading responsiveness,
Stop during retries/chunks/pre-save, close settlement, partial-result retention
and refusal of source changes between preview and Accept. Cover cancel pickers,
duplicate import, invalid config/cards/preset, empty outline, no key, 404/unavailable
limits, missing tags/no candidates, force decline/accept, retained trees and dirty
project switching. No live HTTP, silent Qt skip or weakened guard.

The final task verifies all new cases are actually invoked by the existing
offscreen wrapper and pytest discovery in `./scripts/check.sh`, retaining syntax/
help/runtime checks. Record native Wayland results separately (or PENDING):
platform/runtime/compositor, Create/Open/preset pickers, forms, keyboard/clipboard,
focus/resize, available scaling/themes, planner progress/Stop/close and reopen.
Existing shell smoke and offscreen tests do not establish this acceptance.

## Risks / Trade-offs

- [Broad settings surface] -> Explicit supported paths and headless domain tests;
  preserve unknown config instead of silently deleting it.
- [Freeform bible cannot be reverse parsed safely] -> Keep saved forms separate,
  show current body and require explicit acceptance; allow direct section edits.
- [Shared chat extraction can alter CLI transcripts] -> Freeze each path first;
  optional hooks keep default CLI behavior, existing prompts and persistence.
- [Late cancellation or multi-file failure] -> Retain already saved work, report
  exact outcomes; existing file saves are not cross-file transactions or locks.
- [Concurrent external writers] -> Exact baseline checks refuse detected changes;
  simultaneous CLI/GUI writing remains unsupported under ADR-0007.
- [Desktop coverage unavailable in automation] -> Leave real Wayland evidence
  explicitly pending, without claiming shipping or whole-workspace completion.

## Migration Plan

No data migration. Land the eight test-first tasks incrementally on the current
feature branch; existing CLI and drafting stay usable with old project files.
Rollback presentation/shared-operation changes without converting data: all
new outputs remain ordinary existing JSON/Markdown files. Mark milestone 2
implemented only after its build checks and honest acceptance record; continuity/
review/export remains a later selected change, not part of this proposal.

## Open Questions

None blocking build. Additional compositor/monitor combinations are optional
acceptance details, not unresolved behavior or architecture.
