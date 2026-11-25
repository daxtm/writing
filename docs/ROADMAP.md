# Roadmap

## Goal

Make `longform.py` safe to change through observable offline regression tests,
then extract only the boundaries the prototype actually needs. Preserve
`uv run --script longform.py …` and existing project files and reports.

Extend that foundation into a polished Linux desktop writing workspace:
run the existing planning, drafting, review, and export flow through buttons,
with a persistent multiline steering box and native Wayland support. The CLI
remains available and uses the same writing operations and project files.

The next owner-requested extension is a beginner-friendly, guided workspace:
every new project gets the owner's sanitized configuration and writer preset,
GUI Create performs complete initialization, API keys can be entered in the
GUI, and a resumable wizard leads through bible, outline and scenes into
drafting, review and export. All provider-generated answer text appears while
it arrives, including multiple candidates, rather than only when a call finishes.

## Out of scope

New model/provider capabilities, autonomous whole-book generation, browser/server
interfaces, cloud accounts, collaborative concurrent editing, rich-text/DOCX
editing, standalone installers, private sample/preset fixtures, and live API
tests. Existing CLI capabilities becoming GUI controls are in scope; changing
their prompts, sampling policy, or file formats is not. Dependency provisioning
may use network; test execution must not.

For this extension, replacing new-project defaults and adding explicit GUI
credential entry are intentional exceptions to the earlier frozen-default and
credential-name-only scope. Existing projects are not migrated or reset.
The original private project and preset remain outside the repository; only
reviewed, sanitized runtime defaults may be bundled, not private test fixtures.
No new toolkit, provider, model capability, secret-service dependency, automatic
paid pipeline, key synchronization, installer or shipping authorization is added.

## Next extension — Guided writing workflow

This section supersedes the earlier instruction to stop planning after GUI
milestone 3, and its credential-name-only/completion-based-progress limitations.
The implemented milestone/history sections below remain baseline evidence,
not acceptance of this extension. No OpenSpec change directories are created
for these roadmap items; select one for build before writing its artifacts.

### Milestone 1 — Walking skeleton: initialized project to live outline

- [ ] project-defaults-full-init — Fix shared CLI/GUI init to create every initial file/directory plus a usable bundled writer preset, using the owner's sanitized project defaults; cover immediate and deferred GUI Create paths and copied-executable resource loading.
- [ ] gui-api-key-setup — Extend existing Setup/settings and shared provider construction with masked session-key entry and explicit local-project Save/Replace/Clear, missing/available status and an explicit Test connection action; never copy credentials into defaults.
- [ ] gui-generated-text-streaming — Extend existing Api callbacks, candidate batching, shared operations and the one worker so every generated answer streams into its owning preview, including planner, writer, summarizer, critic and editor calls and every candidate.

**Observable slice:** launch
`QT_QPA_PLATFORM=wayland uv run --script longform.py gui /path/to/new-project`,
choose Create, inspect complete local setup without a preset picker, enter a
key, save bible answers using the existing forms, then Generate an outline.
The first answer chunks appear before completion; the author explicitly
chooses a completed candidate. No terminal, external preset path, manual JSON
editing or environment export is required. This is the walking skeleton,
not the completed wizard or redesigned workspace.

**Defaults contract:** the read-only sources are
`/home/daxtm/Documents/fuckpi/project.json` and
`/home/daxtm/Documents/fuckpi/56295265-LLam_ception-1.3.json`.
Read them only when preparing the implementation's reviewed defaults, never
at app startup, build time or test execution. Copy supported nonsecret project
settings and the validated master-export preset into application-owned runtime
resources. Force `api_key` empty, `api_key_env` to `FEATHERLESS_API_KEY`, and
`roles.writer.preset` to project-relative `writer_preset.json`; keep the
source's other supported defaults, including model/sampler/prompt settings.
Use the chosen project title when supplied, otherwise the source's Untitled
default. Review all nested values for credentials/private data before tracking
derived assets. Record source provenance and preset notices without including
the original private files. Never use the owner's source files as test fixtures.

Full init means the existing five files and seven directories plus the default
`writer_preset.json`, not implicit bible/outline/scene generation or limits
fetching. Both adapters use the same operation. Existing files/presets are
never overwritten; repeated init only fills missing paths. Explicit CLI
`--preset FILE` overrides the bundled preset only when creating a missing
destination. Existing configured external paths are not silently rewritten.
Open remains read-only. Report collisions and partial-init failures truthfully;
retry fills missing paths without resetting prior work.

**Streaming coverage:** outline Generate/Reroll (N candidates), scene
Generate/Regenerate, draft Generate/Reroll/Add N, continuity full/summary-only,
compression, critique and revision/Regenerate all show answer deltas before
completion. Bible answers currently compose locally with no provider request;
the wizard must not invent an AI bible call. Show waiting/thinking status
before answer tokens, not fabricated text or a blank unexplained box.
Incomplete JSON/tagged responses are provisional raw previews; existing parsers
and acceptance gates run on the completed answer. Candidate and retry-attempt
identities prevent mixing fragments; retries reset only the affected preview.
Keep hidden reasoning separate, Stop/close cooperative, controls responsive,
existing completed saves intact and partial answers out of accepted files.
Preserve existing final-output parsing, prompts, samplers and CLI transcripts.

**Acceptance:** offline paused fake streams prove intermediate text is visible
while a request is still blocked, for each operation family and concurrent
candidate, including retry/Stop/failure. Synthetic secret sentinels prove no
credential reaches events, logs, errors, export or bundled defaults. Fresh
source/frozen CLI init results agree away from the checkout with the owner's
source paths unavailable. GUI Create and deferred Create produce the same
complete result. Add all tests to `scripts/check.sh`; real native Wayland
credential entry, live previews, Stop/close and focus remain separate desktop
acceptance, not inferred from offscreen results.

Milestone 1 forces [ADR-0010](adr/0010-sanitized-new-project-defaults.md),
[ADR-0011](adr/0011-gui-project-credentials.md) and
[ADR-0012](adr/0012-shared-generation-stream-events.md).

### Milestone 2 — Guided setup and a coherent writing workspace

- [ ] gui-workflow-navigation — Rework the existing Qt window into Plan → Write → Review → Export navigation with a project overview, plain-language readiness/next actions, focused stage layouts and context-only generation/steering controls; retain every existing advanced action through secondary panels and update the parity map.
- [ ] gui-project-setup-wizard — Compose shared init/settings/bible/outline/scenes operations into a back/next, save-and-resume wizard: location/title and defaults → credentials → bible questions → generate/choose outline → generate/edit/accept scene cards → enter the first unfinished scene, with streaming previews, explicit paid actions and acceptance.

The wizard launches after successful new-project Create and can be reopened
for incomplete projects. It uses saved project artifacts/answer histories to
derive readiness rather than a second authoritative project format; no hidden
wizard-only document owns bible/outline/scenes. Back/Next never generate, accept
or discard edits implicitly. Save/Discard/Cancel resolves dirty forms; leaving
and reopening resumes saved work and shows incomplete prerequisites. Replacing
an outline or scene plan explains downstream impact and preserves existing
history/trees under the existing confirmation rules. Manual planning and the
advanced controls remain available; the wizard is guidance, not a lockstep
requirement for existing writers.

Each stage identifies what it does, what input is missing, where output goes
and the one primary next action. Move the always-visible draft steering and
Generate controls into Write; do not show a wall of fifteen equal-priority tabs.
Keep scene/branch navigation, candidate selection, lore, exact prompts, settings,
continuity, revision, reports and destination-picked export discoverable.
Review/Export can be entered deliberately; readiness warnings explain concerns
without inventing new mandatory review gates or automatic model calls.
Keyboard navigation, focus order, labels, empty/error states, resize/scaling and
light/dark readability are acceptance criteria within these two changes, not
a later polish milestone.

**Acceptance:** a first-time user follows visible instructions from a missing
directory through credential setup, accepted bible/outline/scenes, streamed
draft candidates and Accept, continuity/review/revision and picked export, with
no terminal/config/preset knowledge. An offline offscreen journey uses
synthetic credentials, fake streams and interruption/reopen checks; the full
existing CLI/GUI action parity map is re-audited. `scripts/check.sh` runs the
journey and all new regressions. Record a separate real Wayland walkthrough
including keyboard, pickers, scaling/theme and Stop/close before claiming this
extension complete; an unavailable desktop leaves acceptance explicitly pending.

**Open questions:** no blocking product choices remain. Exact visual styling
can be decided in the selected navigation change against the above journey.
Encrypted/system-keyring storage and a shared key across projects are not
implied by API-key entry; ADR-0011 deliberately retains existing per-project
storage with an unsaved-session alternative.

## Planning baseline and completion bar

The owner's completion bar is **every feature the CLI/TUI has, start to finish,
must exist in the GUI**. No individual change below completes the workspace.
Completion requires the entire three-change remaining sequence, command/action
parity tests, the from-empty-project through export demo and separate real
Wayland acceptance. This plan does not authorize shipping.

The Qt reading/steering shell is implemented but unshipped on
`feat/gui-wayland-shell`; it integrates the reader snapshots and ADR-0004/0005.
Do not confuse that branch with `origin/main`. Its existing
`openspec/changes/gui-wayland-shell/` records the shell, not working generation.
The complete draft loop is implemented on this branch (real drafting Wayland
acceptance remains pending). Milestone 2 is now implemented on this branch:
`openspec/changes/gui-project-planning/` has its eight tasks landed
(Create/Open through saved scene cards, offline parity and offscreen journey
coverage; real Wayland Create-to-scene acceptance recorded as PENDING in
`openspec/changes/gui-project-planning/evidence.md`). Milestone 3
(`gui-continuity-review-export`) is now selected/proposed in
`openspec/changes/gui-continuity-review-export/`, with eight unchecked test-first
tasks. It is not implemented; this proposal does not authorize shipping.
Stop planning after this final change: after implementation, audit the full
parity matrix below before any whole-workspace completion claim.

The existing `cmd_*` commands already implement the rules. Fix/extract those
boundaries, keeping CLI adapters and reusing `Project`, `Tree`, `Lore`, prompt/
check helpers and `Api`. Terminal input, `$EDITOR`, paging and blocking calls
cannot serve desktop controls; neither a duplicated writing engine nor terminal
automation is acceptable. ADR-0007 governs shared operations and one background
worker throughout the sequence.

## GUI milestone 1 — Walking skeleton and complete drafting workspace

- [x] gui-wayland-shell — Native Wayland Qt reading shell: safe snapshots, all saved branches/notes, state-preserving refresh and persistent steering Save/Clear; implemented, unshipped, no generation yet.
- [x] gui-drafting-workspace — Complete the draft loop: shared operations, one worker, Generate/swipes/reroll/add/progressive display, Accept/keep/discard/delete, Stop/safe close/stale protection, length/POV/cast/card/context/exact prompt, manual edit/history/rewind/jump/tree/tail, lore management/import and scene done.

This consolidates the former `gui-steered-drafting` and `gui-draft-controls`;
neither is a separate future change. The shell is the walking-skeleton baseline,
not completion. PySide6 6.12.0 and offscreen widget tests are already in the
launcher/check environment. Its real Wayland smoke is recorded in the shell
design (KWin/Plasma 6.8.3, `wayland`, 1920×1080 DPR 1.0, persisted steering,
clean close); interactive scaling, themes and mouse/keyboard acceptance remain.
The source launcher and the copied executable also open this workspace when
invoked with no command (for example a file-manager double-click), defaulting
the project directory to the current directory; explicit commands still require
their existing arguments.

Drafting starts from an existing synthetic project with preset and planned
scenes. Generate saves current multiline steering before building the shared
prompt; default swipes or explicit N create complete saved candidate branches,
not accepted text. Only Accept (or explicit branch/manual operations) changes
head. Reroll keeps old nodes, Keep branches/Discard preview never deletes saved
prose, Delete uses existing leaf semantics. Preserve all metadata, histories,
separators, warnings and CLI prompt/sampler/file parity. Prompt inspection
includes budgets, actual samplers, injected lore, exact preview and `last_prompt.txt`.
Lore JSON/PNG imports use desktop pickers and existing validation.

One project operation at a time, queued worker signals, GUI-only widget updates,
reading usable during work and conflicting writes disabled. Stop is cooperative
at request/stream/save boundaries with existing request timeouts, never thread
kill; no partial passage saves or failure-induced head changes. Close offers
Stop and wait / Keep open and waits for worker settlement without freezing the
UI. Saved complete branches survive Stop/failure. Compare captured inputs before
writes, refuse stale/unsafe targets, preserve dirty editors; concurrent CLI/GUI
writers remain unsupported.

Observe after implementation:
`QT_QPA_PLATFORM=wayland uv run --script longform.py gui /path/to/project`.
Set steering/length/cast, inspect the exact prompt, Generate two candidates,
reroll/add/view and Accept. Write/edit manually, rewind/switch branches, import/
toggle/classify lore, mark done and reopen to see saved text/history/branches.
Fake-provider failure/Stop leaves prior head/branches intact and controls usable.
This demonstrates drafting only, not setup-to-export GUI completion.

## GUI milestone 2 — Setup and planning

- [x] gui-project-planning — Implemented on `feat/gui-wayland-shell` (unshipped; real Wayland acceptance PENDING): Create/Open and init, preset import, models/roles/settings, explicit limits fetch, bible sections/answers/history, outline notes/N candidates/reroll/choice/edit, scene generation/view/edit/replace confirmation and saved-card editing.

Depends on drafting workspace; this is remaining change 2, not a draft-controls
follow-up. Use existing initialization and validation/non-overwrite behavior,
bible fixed-question forms with answer/edit/accept/skip/quit choices, outline
notes and candidate loops, scene validation and explicit force/replace choices.
Built-in plain-text Save/Cancel panes replace terminal editors; no implicit paid
call or automatic next command. A settings form exposes supported nonsecret
models/roles and configuration; credentials use the existing environment
mechanism, showing only variable name/missing-key status, never an existing key.
Desktop preset picker retains existing master-export validation.

Observe after implementation: launch the GUI for a missing directory, Create,
choose models/preset, fetch limits, fill bible sections, generate/re-roll/select
an outline, generate/edit/accept scenes and enter the complete drafting loop.
The same offline temporary-project/fake-provider test compares CLI prompts and
saved outputs; no terminal prompts or external editors.

Implemented (tasks 1.1–1.8 on `feat/gui-wayland-shell`): the offscreen journey
`case_planning_journey` runs missing-DIR → Create → preset import → settings →
explicit limits fetch (fake Api) → bible answers/accept → outline
generate/reroll/choose → scenes generate/edit/accept → Draft selection →
reopen with no terminal/editor helper and no implicit provider request.
CLI/GUI parity is frozen at the file/prompt/history level for init, bible,
outline and scenes (`tests/test_planning_ops.py`); `limits.json` matches the
CLI shape modulo `fetched`. Real Wayland Create-to-scene acceptance
(pickers/forms/keyboard/scaling/themes/Stop/close) is recorded as PENDING in
`openspec/changes/gui-project-planning/evidence.md`.

## GUI milestone 3 — Continuity, review, revision, status and export

- [x] gui-continuity-review-export — Implemented on `feat/gui-wayland-shell` (unshipped; real Wayland acceptance PENDING): update-state/summary-only previews/edit/regenerate/accept/quit and warnings; compress ranges/replace/edit/accept; critique/check/review-note editing; revise diff/accept/skip/edit/regenerate/quit; status and destination-selected export.

Implemented (all eight tasks on `feat/gui-wayland-shell`, unshipped). Depends
on setup/planning; this change consolidated the former `gui-continuity-review`
and `gui-check-revise-export` roadmap items. Reuse the worker and
shared-operation boundary, not a new job system. Preserve
state_history, summaries, stale/earlier-scene warnings, arc overlap checks,
revision history and existing report/export formats. Status and notes remain
visible; saves refresh affected views without losing position or dirty input.
Replacement/destructive choices name their target and retain confirmation.
The selected proposal/design/spec/eight (all completed) tasks are in
`openspec/changes/gui-continuity-review-export/`; ADR-0007 already governs this
work, so no new ADR/dependency/schema is required. Full-state and arc previews
never implicitly commit; report saves and passage acceptance remain explicit.
Arc history retains existing edited-input versions, not a new automatic arc
snapshot store. Status must not trigger lore-discovery writes. Real Wayland
M3 acceptance is PENDING, separate from future offscreen test results.

Observed implementation (tasks 1.1–1.8 on `feat/gui-wayland-shell`): the
offscreen journey `case_review_journey` runs completed scenes → continuity
preview/Accept → summary-only recovery → compress → critique/check/reports →
revise Accept/Skip → status → picked export → reopen, with file parity against
fixed-clock CLI fixtures (`tests/test_review_ops.py`, 57 tests). One-worker
settlement, dirty-source Save/Discard/Cancel before Revise/Export and
Stop/commit-group behavior are covered by `case_review_settlement` and
`case_review_dirty_sources`. `./scripts/check.sh` runs every headless and
offscreen case (unregistered-case guard), 381 tests + 38 offscreen cases green;
failure injection (missing Qt, failing journey) fails the check instead of
skipping. Real Wayland review/export acceptance (pickers, keyboard, scaling,
themes, Stop/close during review) is recorded as PENDING in
`openspec/changes/gui-continuity-review-export/evidence.md`.

After implementing this final change, the full-parity matrix across
milestones 1–3 was audited row by row against actual controls, headless/
offscreen tests and evidence (see
`openspec/changes/gui-continuity-review-export/evidence.md`): every row maps
to real executed controls and tests; documented deviations are completion-based
progress (nonstreaming `Api.chat`), unsupported concurrent CLI/GUI writers, no
terminal/editor helpers, credential-name-only forms, and per-scene all-check
scope. Explicit remaining gap: separate real Wayland acceptance for all three
milestones. This audit does **not** mark the workspace complete and no
shipping is authorized; no more speculative changes.

## Full-parity coverage map — no CLI command or draft action left behind

| Existing CLI surface | Required GUI control(s) | Workflow route | Case | Implementing change |
|---|---|---|---|---|
| `gui [DIR]` | Native Wayland project window, reading/notes, refresh/navigation, font size; no-argument launch opens it in the current directory | window: Plan/Write/Review/Export stages, sidebar, refresh/prose size (global) | `case_workflow_stages`, `case_owner_flow_reading` | Existing shell; retained throughout |
| `draft [--scene ID]`, resume/default next unfinished | Select scene / Next unfinished / reopen done scene, resume head, status/prerequisite warnings | Write → scene | `case_draft_scene_context`, `case_workflow_stages` | `gui-drafting-workspace` |
| `g [N]` / `gN`, default writer.swipes | Generate, count, streaming/completion progress, Stop | Write → draft (Stop global) | `case_draft_generate_acceptance`, `case_stream_draft_candidates` | `gui-drafting-workspace` |
| Candidate `K`, `r K…` / `r all`, `+ N`, `v K`, `d K`, Enter | Accept, Reroll selected/all, Add N, View, Delete leaf, Keep branches/Discard preview | Write → draft (tray) | `case_draft_candidate_tray` | `gui-drafting-workspace` |
| `s TEXT` / `s -` / `se`, `l N`, `who`, `pov` | Multiline steering Save/Clear/capture, passage length/token cap, cast/POV forms | Write → draft (steering), scene | `case_owner_flow_steering`, `case_workflow_dirty_busy` | `gui-drafting-workspace` |
| `w`, `e`, `r`, `t`, `j ID`, `x ID` | New passage, Edit head/diff/history, Rewind, full branch tree/metadata, Jump/Use as head, Delete leaf | Write → manuscript/branches | `case_draft_edit_and_branches` | `gui-drafting-workspace` |
| `v`, `v ID`, `tail [N]`, `card`, `c`, `cp` | Marked manuscript, full node viewer, Tail N, scene card, context/budget/sampler/injected-lore panel, exact prompt preview/Save last_prompt.txt | Write → manuscript (marked/tail), context, scene | `case_draft_scene_context` | `gui-drafting-workspace` |
| `lb`, `lb N…`, `lb all on/off`, `char NAME`, `alias A,B`, `world`; lorebook/card files | Lore list, individual/multi/all toggles, character name/aliases/world, JSON/PNG import picker | Write → lore | `case_draft_lore` | `gui-drafting-workspace` |
| `d`, scene-end confirmation, `q`, `?` / `h` / `help` | Mark done/decline end suggestion, Leave draft, action help; dirty-editor Save/Discard/Cancel | Write → draft, scene | `case_draft_help_and_leave`, `case_workflow_dirty_busy` | `gui-drafting-workspace` |
| `init [--preset FILE]`, project configuration | Create/Open directory, preset picker, models/roles/settings forms | Plan → setup | `case_planning_create_open`, `case_planning_deferred_create` | `gui-project-planning` |
| `limits`, `bible` | Fetch/display limits, section question/answer/edit/accept/skip/quit forms/history | Plan → setup (limits), bible | `case_planning_settings_limits`, `case_planning_bible` | `gui-project-planning` |
| `outline --n --notes`, candidate selection/new notes/reroll/view/quit | Count/notes editor, Generate/Reroll, candidate viewer/selection, Cancel | Plan → outline | `case_planning_outline` | `gui-project-planning` |
| `scenes [--force]`, view/regenerate/accept/quit | Scene cards list/editor/validation, Generate/Regenerate, Accept/Replace confirmation, Cancel | Plan → scenes | `case_planning_scenes`, `case_planning_card_edit` | `gui-project-planning` |
| `update-state [--scene] [--summary-only]`, invalid raw edit/retry, warnings | Scene/summary-only selection, diff/raw editor, Accept/Edit/Regenerate/Cancel, warning confirmation | Review → continuity | `case_review_update_state`, `case_review_dirty_sources` | `gui-continuity-review-export` |
| `compress --from --to [--replace]` | Range/overlap validation, Replace confirmation, preview/Edit/Accept/Regenerate/Cancel | Review → continuity | `case_review_compress` | `gui-continuity-review-export` |
| `critique --scene`, `check [--scene]` | Critique, Check scene/all, report viewer/editable review notes | Review → reports | `case_review_reports` | `gui-continuity-review-export` |
| `revise --scene` | Per-passage diff, Accept/Skip/Edit/Regenerate/Quit, saved revision history | Review → revision | `case_review_revise`, `case_review_settlement` | `gui-continuity-review-export` |
| `status`, `export [--out FILE]` | Project status, Export with destination picker | Export → status | `case_review_status_export`, `case_review_export_enterable_with_warnings` | `gui-continuity-review-export` |

Every route column names the actual stage → tool path after
`gui-workflow-navigation`; `case_workflow_parity` audits each row's named
controls through those routes, `case_workflow_readiness` covers the Plan
overview/next-action facts and `case_workflow_presentation` covers keyboard,
window sizes, font, palette and offscreen scale 1/2. The end-to-end journeys
(`case_planning_journey`, `case_review_journey`, `case_owner_flow_reading`)
still cover Create → planning → draft → review → export across stages.

The sequence is drafting workspace -> setup/planning -> continuity/review/export.
Do not tick future work based on its proposal. Every row of the map is now
implemented through GUI controls with offline parity coverage (audited row by
row in `openspec/changes/gui-continuity-review-export/evidence.md`), but the
finish line still requires separate native Wayland acceptance for all three
milestones; no offscreen result or shell smoke establishes it.

## Delivery rules for every GUI change

Create its OpenSpec proposal only when that change is selected for build. Keep
each change to at most eight test-first tasks: the first proves the visible
behavior and initially fails; the last makes `scripts/check.sh` run the new
coverage. Preserve existing offline network guards and CLI parity tests. Model
and operation tests always run headless; Qt widget tests use the offscreen
platform in a subprocess with the GUI runtime installed and must not silently
skip missing dependencies. Real Wayland checks are a separate required desktop
acceptance step; document unavailable compositor coverage rather than claiming
headless success proves it. No separate hardening/polish milestone is planned.

## Decisions and acceptance details

[ADR-0006](adr/0006-wayland-writing-workspace.md) selects Qt Widgets/native
Wayland; [ADR-0007](adr/0007-shared-writing-operations.md) selects shared
operations/one worker. These already decide the boundaries; this consolidation
needs no new ADR, data format or dependency. Do not edit accepted ADRs merely to
rename old roadmap IDs.

KWin/Plasma 6.8.3 and PySide6 6.12.0/DPR 1.0 are recorded for the shell, not
whole-workspace acceptance. Record real Wayland platform/runtime/compositor,
100%/200% plus available fractional/mixed-monitor scaling, light/dark themes,
clipboard/focus/resize, file picker and worker Stop/close results separately.
Missing compositor coverage remains explicit; do not weaken Wayland startup
policy or infer compositor support from offscreen tests. No blocking product
choices remain; preferred font/additional monitor combinations are optional
owner acceptance details.

## Phase 0 — Walking skeleton: source, checks, and project facts

- [x] testing-foundation — Track the CLI, replace scaffold checks with real syntax/help/test discovery, and record project facts and this plan on `chore/testing-foundation`.

Source, checks, and documentation landed in `09bb632`, `2609c34`, and PR #1. At
the time, `./scripts/check.sh` showed `== syntax`, `== cli smoke` when uv exists,
and an explicit `no tests/ yet` message until Phase 1. Without uv, syntax still
runs and help is explicitly skipped.
`uv run --script longform.py --help` prints the available commands without an API key.

## Phase 1 — Offline regression suite

- [x] add-test-suite — Run deterministic pytest coverage of helpers, branch trees, reports, and mocked API behavior.

Cover `clean_continuation`; `key_match`, `entry_triggered`, `name_variants`;
`split_bible`, `join_bible`; `extract_json_array`, `extract_tagged`;
`writer_sampling`, `render_story_string`; and `Tree` operations including
save/reload. Extract a pure banned-phrase/n-gram report helper from `cmd_check`
only as needed, preserving its output. Test `Api` via `httpx.MockTransport`,
using synthetic streams, fake projects/clocks/sleep, and no real credentials.
`tests/conftest.py` puts the repository root on `sys.path`; no packaging yet.

Observe with `uv run --with pytest --with httpx pytest -q tests`: tests are
collected and report `N passed`, exit 0. `./scripts/check.sh` adds `== tests` and
the same passing summary. Test failures must fail the script. Checks run
locally; no CI workflow is involved.

## Phase 2 — Extract pure core pieces behind tests

- [x] extract-pure-core — Separate remaining calculation from I/O in place, prioritizing deterministic checks, card/lore parsing, and prompt assembly.

Reuse existing pure helpers and the Phase 1 checker; do not extract them twice.
Keep the script and CLI shape unchanged. Add focused tests before each necessary
extraction; move filesystem/network orchestration outside those helpers.
Observe with `uv run --with pytest --with httpx pytest -q tests` and
`./scripts/check.sh`: both stay green, with identical fixed-fixture reports and
prompt strings before and after extraction.

Extracted boundaries (each behind a test-first commit): `card_png_json(data)`
plus a thin `read_card_png` wrapper (`tests/test_card.py`), `parse_book_data(d,
stem)` plus a thin `parse_book` wrapper (`tests/test_book.py`),
`layered_summary_core(sums, cfg, …, est, root)` plus a thin `layered_summary`
wrapper (`tests/test_summary.py`), and `compose_writer_prompt` /
`tail_trim_chars` split out of `build_writer_prompt` (`tests/test_writer_prompt.py`
with a stored `tests/data/writer_prompt_fixture.json` parity fixture covering
scene start, continuation, and steer).

## Phase 3 — Package split

- [x] split-cli-package — Move the tested implementation into a package while retaining the thin uv launcher.

The owner asked to split now despite the gate check below coming back "not
triggered"; ADR-0003 supersedes ADR-0002 to record that deliberate override.
`longform.py` stays at the repo root as a thin PEP 723 launcher re-exporting
the public names; the implementation moved to `longform_core/` (`config`,
`utils`, `project`, `api`, `tree`, `lore`, `prompt`, `checks`, `commands`,
`cli`) as a move-only refactor.

Result: `uv run --script longform.py --help`, the full offline suite, and
`./scripts/check.sh` all stay green with byte-identical CLI help and
fixed-fixture reports/prompts; 154 tests pass. One-file portability is
sacrificed even though the launcher command stays the same.

## Decisions

- [ADR-0001: Record architecture decisions](adr/0001-record-architecture-decisions.md).
- [ADR-0002: Keep the single-file CLI through the prototype](adr/0002-single-file-cli.md)
  accepted the prototype trade-off and defined extraction/package triggers;
  superseded by ADR-0003.
- [ADR-0003: Split the CLI into a package now](adr/0003-split-into-package.md)
  records the owner's deliberate override of the ADR-0002 gate and the package
  layout.
- [ADR-0006: Use Qt Widgets for the Wayland writing workspace](adr/0006-wayland-writing-workspace.md).
- [ADR-0007: Share writing operations between CLI and an asynchronous GUI](adr/0007-shared-writing-operations.md).

ADR-0004/0005 are already allocated on `feat/reader-gui`; keep those numbers
and records when integrating it rather than reusing them on this roadmap branch.
