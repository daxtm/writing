# Design

## Context

See proposal.md — Why. `project-defaults-full-init` is implemented.
`gui-api-key-setup` and then `gui-generated-text-streaming` must land first so
reparented controls retain their tested behavior; `gui-project-setup-wizard`
follows this change. This is a presentation refactor, not a
second operation layer.

`MainWindow._build_ui` creates fifteen `self.tabs` pages plus a globally visible
steering box. `_build_*_tab` methods build reusable controls; widget tests select
pages with the existing numeric tab constants. `_wire_tab_order` assumes the old layout.
`_on_selection_changed`, `refresh`, `_update_panes`, dirty resolvers and the
single `_dispatch`/worker settlement gate already preserve writing state.

Use `planning_operations.project_overview`, `bible_overview`,
`outline_overview`, `scenes_overview`, `draft_operations.session_info`/
`scene_overview`, `review_operations.status_facts`/`full_status` and sanitized
`reader_model` snapshots for guidance. `project_overview` currently counts some
file existence as presence; that alone is not evidence of accepted story content.

## Goals / Non-Goals

**Goals:** focused stages, plain-language recovery, retained full action parity
and live previews, keyboard/presentation acceptance within this change.

**Non-goals:** provider/engine refactor, new saved navigation/project format,
wizard, automatic workflow sequencing, mandatory reviews or changed prompts.

## Decisions

### Reparent existing controls into four stable stage routes

Use a four-item primary selector and stacked stage pages inside the existing
window. Keep `MainWindow`, current widget fields and business-action methods;
move pane widgets instead of recreating duplicate editors. Give routes semantic
keys (`plan`, `write`, `review`, `export`) and stage-local tool keys rather than
numeric indices. Replace test `tabs.setCurrentIndex` calls and the shell's
tab constants with semantic stage/tool routing; bind new overview actions to
those routes. Existing settlement handlers must keep updating their owning
panes without stealing the selected stage. Do not retain an invisible fifteen-tab compatibility wall.

Keep Create/Open/Refresh/prose size and global labelled operation status/Stop
on the shared shell. The scene/branch sidebar remains available for reading;
selection must not launch generation. Plan is the initial page for missing or
incomplete planning; a ready project can open Write at its saved/default
unfinished scene using existing selection rules. Never auto-open a modal wizard
here; reserve the visible Plan “Resume setup” location for the next change.

| Stage | Focused default | Labelled secondary routes / reused builders |
|---|---|---|
| Plan | Overview with one recommended next action | Bible (`_build_bible_tab`), Outline, Scene plan (`_build_scenes_tab`), Project settings/credentials/limits/preset (`_build_setup_tab`) |
| Write | Manuscript + scene-labelled steering + candidate preview/tray | Scene details/POV/cast/session length/done/Next unfinished, Branches/manual editor/history/marked/Tail, Context/exact prompt, Lore/import, Notes, draft Help/Leave |
| Review | Continuity and review readiness for selected scene | Continuity/full/summary-only/compression/history (`_build_continuity_tab`), Reports/critique/check/edit (`_build_review_tab`), Revision/diff/Accept/Skip/Edit/Regenerate (`_build_revision_tab`) |
| Export | Destination-picked Export and saved word count | Full read-only status (`_build_status_tab` contents), manuscript preview and advisory readiness concerns |

Secondary routes are labelled tool lists/expanders within the active stage;
not fifteen primary tabs. Keep one editor instance per source and retain it
when hidden. Move steering/count/Generate from `_build_ui` into Write beside
the existing `preview`/candidate tray. Stop stays global because requests may
remain active while browsing another stage.

Alternative rejected: merely rename four tabs while leaving eleven additional
peer tabs or always-visible Write controls. That preserves the confusion and
does not meet the observable four-stage contract.

### Derive advisory guidance from saved facts, not a new workflow state

Extend existing read-only overview helpers with plain facts needed by both
Plan and the subsequent wizard. Keep them Qt-independent and sanitized.

Readiness rules:

- Init: supported valid saved configuration and complete local initial paths/
  usable preset from the already implemented initializer.
- Credentials: current effective availability/source from credential change,
  separate from saved-content readiness; missing keys do not gate local tools.
- Bible: nonplaceholder accepted section content using `bible_overview` and
  `commands.is_placeholder`; list remaining template sections as advisory.
  Do not require every section before a planner call that currently accepts
  partial work.
- Outline: nonempty saved working `outline.md`, excluding candidate notes
  comments/template-only content; unchosen candidates do not qualify.
- Scenes: valid saved nonempty cards and their existing normalization/status,
  not just a `scenes.json` path or raw provisional response.
- Write/review/export: active-chain words/head, first unfinished scene,
  existing summary freshness/report facts; no reading-induced lore discovery.

For Plan's primary next action, choose the first applicable recovery:
Create/repair missing setup by explicit action → credential entry for generated
planning (with manual alternative) → local bible → saved outline → saved cards
→ Enter Write. If a source is invalid, show its error/recovery before dependent
steps rather than zero/complete defaults. Readiness is advisory and cached only
as view data; refresh recomputes it from saved sources. The wizard will reuse
these facts instead of introducing another authoritative state.

Review/Export remain explicitly enterable. Export retains existing source/
destination validation and dirty-source resolution; missing optional critique
or stale summaries produce advice, never a new mandatory gate or paid call.

Alternative rejected: page-visited flags or a durable stage state file; neither
tracks CLI/manual edits or accepted versus provisional output correctly.

### Preserve existing lifecycle and dirty-state semantics

Follow [ADR-0007](../../../docs/adr/0007-shared-writing-operations.md).
Retain [ADR-0011](../../../docs/adr/0011-gui-project-credentials.md) credentials
and [ADR-0012](../../../docs/adr/0012-shared-generation-stream-events.md)
preview identities. A stage change only changes view/focus; it cannot change
`_op_kind`, current request identity or captured source/scene.

Hidden editor widgets keep their text/cursor/scroll and baseline. If a route
would replace their source/selection, use `_resolve_dirty`,
`_resolve_saved_sources`, `_resolve_review_dirty`, `_resolve_report_dirty` and
`_resolve_rev_dirty` as appropriate. Failed/stale saves cancel the route;
async saves defer it until actual successful settlement. Do not dispatch a
paid next step from an overview refresh. Late events remain operation-bound,
not routed by the newly selected stage. Preserve the one-worker gate through
thread finish and make global Stop/status visible during every operation.

### Accept keyboard, labels and presentation now

Give stage selectors and tools accessible names/mnemonics and meaningful
focus policies; navigation puts focus on the stage heading/primary action
without destroying an editor's remembered position. `_wire_tab_order` becomes
stage-aware: primary selector → active tool selector → active content → local
actions; global Stop remains reachable when enabled. Enter in multiline
editors never triggers a default button. Explain disabled actions in visible
text, not just tooltips.

Use existing system palette roles, native controls, scrollable forms and
stretching splitters. Check 900×600 and existing 1150×760 offscreen window
sizes, larger font/prose values, light/dark palettes and focus order. Run
offscreen subprocess presentation checks with scale factors 1 and 2 without
changing production `gui.resolve_platform`: only direct widget tests use
offscreen. Real Wayland acceptance separately records 100%/200%, available
fractional/mixed-monitor scaling, runtime/compositor, keyboard/clipboard,
pickers, Stop/close and themes. Unavailable desktop evidence stays PENDING.

### Re-audit every parity route

During implementation update `docs/ROADMAP.md` Full-parity coverage map with
stage → secondary tool → actual control → actual case, preserving its complete
row set and leaving extension checklist boxes untouched until actual acceptance.
Use the existing audit in
`openspec/changes/gui-continuity-review-export/evidence.md` as baseline, not
proof that the reparented controls remain reachable. Record changed routes and
remaining native acceptance in this change's implementation `evidence.md`.

## Verification

Register `case_workflow_stages`, `case_workflow_readiness`,
`case_workflow_parity`, `case_workflow_dirty_busy` and
`case_workflow_presentation` in `tests/qt_widget_cases.py`. Reuse the existing
planning/draft/review journeys and fixture fakes but drive controls via stage
routes, not calling action methods to bypass inaccessible widgets. Adapt
`case_focus_and_tab_order`, `case_navigation_no_writes`,
`case_refresh_preserves_state`, palette and existing tool cases to route keys.
Keep `tests/test_planning_ops.py`/`test_review_ops.py` headless readiness tests,
the existing CLI parity suites, `test_gui_dispatch.py` native-platform policy
and the subprocess/registration guards. Every new case runs through
`tests/test_qt_cases.py` and `scripts/check.sh`.

## Risks / Trade-offs

- [An old numeric tab assumption targets the wrong tool] → replace test/tab
  constants with route helpers and exercise overview-action/result routing.
- [Secondary panels hide a CLI action] → row-by-row control reachability audit,
  not a screenshot or handler-only test.
- [Reparenting resets dirty state/streams] → retain widget instances and assert
  text, selection and originating preview across stage navigation.
- [Large forms clip at scale] → scrollable layouts, offscreen scale cases,
  separate real compositor acceptance rather than an aesthetic follow-up.

## Migration Plan

No persisted data migration or new dependency. Ship no engine change under
this proposal. A UI rollback restores the old layout over the same files.
This is a routine reversible presentation choice under existing ADRs, not a
new architecture decision. No blocking open questions or shipping authorization.
