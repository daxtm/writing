# Design

## Context

See proposal.md — Why. Ordering is `project-defaults-full-init` (already implemented) →
`gui-api-key-setup` → `gui-generated-text-streaming` →
`gui-workflow-navigation` → this change. Consume those controls/readiness facts;
do not implement alternate versions of them.

`MainWindow.create_project` and `_run_pending_action` both dispatch shared
`init_project`, with `_pending_root` bound after success. Dirty settings can
defer Create until Save settles. `_rebind_root` resets per-project editing/
preview state. Existing bible/outline/scenes handlers call shared operations,
not terminal commands. Current local bible composition already supports saved
forms, previews and section acceptance; no AI bible call exists.

## Goals / Non-Goals

**Goals:** a visible beginner path over existing actions, correct saved-artifact
resume, explicit provider/acceptance steps and preserved manual access.

**Non-goals:** a second writing pipeline, wizard state schema, auto-generation,
new defaults/resource loading, new credential or streaming protocols.

## Decisions

### Compose existing Plan tools as a guide in the same window

Keep the navigation change's four-stage shell. Create opens a Plan guide
with a step list, heading/instructions, active content and Back/Next/
Save and resume later/Advanced planning controls. Reuse the same settings/
credentials/bible/outline/scenes widget instances or shared presenters; do not
have a separate hidden copy of editors with competing baselines.

Use stable step keys `location`, `credentials`, `bible`, `outline`, `scenes`,
`write`. Expose `setup_back_btn`, `setup_next_btn`, `setup_resume_later_btn`,
`setup_advanced_btn`, `setup_step_label`, and Plan's `resume_setup_btn`.
The location step has a directory picker, title field, nonsecret bundled-
defaults summary and explicit `setup_create_btn` (“Create project”). Next
only navigates/explains missing dependencies; it is never an implicit Generate
or Accept. The final step's explicit “Enter Write” is navigation, not drafting.
Manual planning remains available through Advanced planning/Leave guide.

| Step | Existing boundaries and explicit actions |
|---|---|
| Location/title/defaults | `init_project(root, title=...)`, complete preset/defaults; existing files never replaced |
| Credentials | Credential group from prerequisite change; same session/default, explicit Save/Replace/Clear/Test |
| Bible questions | `begin_bible_session`, `bible_form_state`, `save_bible_answers`, `accept_bible_section`, direct section edit/history; entirely local |
| Outline | `save_outline_notes`, `generate_outlines`, `read_outline_candidate`, `choose_outline`, `save_outline_body` |
| Scene cards | `generate_scene_cards`, `save_scene_cards`, `accept_scene_cards`, baseline/force/replace helpers |
| Write handoff | `next_unfinished`/existing selection and Write route with saved head/steering |

Every step describes what it does, what is missing and its output path. On
outline/scenes use labels such as “Generate outlines (provider request; may
cost money)” and separate Choose/Accept; paid actions never run when opening,
typing, changing pages or accepting the previous step. Use the streaming
change's per-candidate/raw-preview routing, waiting state and parser gates.
No automatic limits fetch is added.

Alternative rejected: driving CLI prompts or adding new wizard operations for
the same prompts/parsers. Shared operations already define those behaviors.

### Integrate immediate and deferred Create without an initialization race

Before leaving an existing project for location setup, resolve dirty old-project
sources through the existing Save/Discard/Cancel flow. Carry the proposed root
and title together in pending Create state; both immediate Create and the
deferred continuation call the same initializer exactly once. Do not bind the
new root or display successful credential step until init settles successfully.
If cancelled/failed, retain the old project/session and report partial init
paths truthfully; retry fills only missing paths. Never inherit old settings/
session credentials as new-project defaults. Successful different-root binding
clears the old session through the credential change.

If confirmed Create targets an existing configuration, its title and settings
are preserved; show that the typed title did not overwrite them. For an
existing project the location page is read-only identity guidance, with title
edits routed to ordinary explicit settings Save rather than reinitialization.
Open stays read-only and displays Resume setup rather than forcing a modal
guide or creating missing paths.

### Resume from saved facts, never “last page completed”

Reuse/extend the navigation change's read-only readiness facts beside the
existing planning overviews. No `wizard.json`, wizard-only answers or hidden
acceptance marker is allowed. Current page can be transient window state;
after reopen choose the first incomplete step from saved evidence:

| Step | Saved evidence / resume behavior |
|---|---|
| Location | Existing valid configuration and complete initial paths/preset; invalid/partial setup shows explicit recovery, never auto-repair |
| Credentials | Effective availability is separate transient capability; missing keys suggest entry but never erase or block local saved work |
| Bible | Accepted nonplaceholder section content; `inputs/bible_answers_<slug>.md` restores forms, not acceptance; remaining optional/template sections are advisory |
| Outline | Nonempty saved working `outline.md`, not unchosen `outlines/candidate_*`; list saved candidate history for explicit selection |
| Scenes | Valid nonempty saved `scenes.json`, not a generated/raw/edited unsaved preview |
| Write | First non-done saved card; all-done gives explicit scene selection, never resets status |

Bible progression follows existing planner requirements, not a new “every
question must be answered” gate. Show remaining sections and Skip choices.
Changing title/bible/outline after later artifacts exist warns that saved
downstream work has not automatically been updated; do not invent dependency
hashes/migration rules to label old work as freshly generated.

Saved raw/edit inputs/history remain viewable using existing functions. A
discarded in-memory scene preview is not reconstructed as accepted cards on
resume. Reopening a completed setup can review any step without regeneration.
Reopening with a lost session key may suggest credentials while retaining all
later saved progress and allowing manual navigation.

Alternative rejected: persist page-completion flags or an independent planning
document; CLI/direct edits and interrupted unaccepted previews invalidate them.

### Resolve dirty edits and replacement consent at existing boundaries

Use `_resolve_dirty`, planning save/discard helpers, `_resolve_saved_sources`
and appropriate review dirty resolvers when leaving guide/project/window.
Within Back/Next, simply hiding an editor can preserve it; if a destination
would replace/reload it, offer Save/Discard/Cancel. Save and resume later
explicitly offers to save dirty forms, waits for successful async saves, then
returns to Plan. Saved answer/edit inputs are not implicit Accept. Failed/
stale Save or Cancel leaves the step/text selected; Discard reloads saved
state. Never put session credentials in resume storage.

Before replacing an outline with downstream saved scenes/trees, add a plain
warning to the existing Choose/Save action naming that scenes/drafts remain
unchanged and are not regenerated/deleted; retain outline-prev backup behavior.
Before scene regeneration with drafted cards/trees, use existing force-equivalent
confirmation; before replacing any nonempty list, use fresh Replace consent.
Name `scenes.json`, existing backup and retained trees. Consent is bound to
the current baseline, not a page-level permanent “force” setting.

### Keep one worker, focused controls and an explicit handoff

Follow fixed
[ADR-0007](../../../docs/adr/0007-shared-writing-operations.md),
[ADR-0010](../../../docs/adr/0010-sanitized-new-project-defaults.md),
[ADR-0011](../../../docs/adr/0011-gui-project-credentials.md) and
[ADR-0012](../../../docs/adr/0012-shared-generation-stream-events.md).
Every network/write action uses `_dispatch` and captured root/baselines;
Back/Next cannot start another operation or retarget a stream. Global Stop
and originating progress remain reachable while reading other saved steps.
Close keeps Stop and wait/Keep open followed by dirty resolution. Preserve
already committed complete work and existing stale/unsafe-target refusal.

Enter Write uses saved first-unfinished selection and existing prerequisites,
not a newly generated passage. No mark-done/state update/head change occurs.
All-done and missing/invalid saved cards show a labelled recovery/manual
selection. Existing manual advanced writing/review/export remain reachable.
The wizard is guidance, not a lockstep prerequisite for existing authors.

Follow navigation's accessible labels/focus/palette/scrollable sizing. Step
navigation focuses its heading/primary control, retains multiline-editor
Enter semantics and visible errors. Do not defer these to another polish item.

## Verification

Register `case_setup_wizard_journey`, `case_setup_wizard_resume`,
`case_setup_wizard_dirty_create`, `case_setup_wizard_replacement` and
`case_setup_wizard_presentation` in `tests/qt_widget_cases.py`. Reuse `_pump`,
scripted choice/directory/save pickers, `PlanningFake`, `FakeProvider`,
`ReviewChatFake` and the prerequisite paused-stream enhancements.

The primary journey starts with no directory/environment credentials, Create
with title/defaults, session key, local bible Save/Accept, two live outlines/
Choose, live cards/edit/Accept, interrupted close/reopen and credential reentry,
then first unfinished Write/streamed candidates/Accept, continuity/review/
revision and picked export. Prove no request outside explicit provider actions
and preview text while the fake stream is still blocked. Never invoke terminal
helpers or use private owner projects/default sources as fixtures.

Headless `tests/test_planning_ops.py` covers readiness across templates,
answer-only saves, unchosen candidates, accepted sources, external edits,
malformed/unsafe sources and no wizard-state file. Preserve existing init,
planning, draft/review CLI/file/transcript parity suites. Exercise deferred
Create, Stop/failure/stale save, both dirty transitions and history/tree
preservation alongside their implementation commits.

`tests/test_qt_cases.py` runs all registered cases offscreen with the existing
network guards; `scripts/check.sh` retains source/frozen stages and cannot
skip a missing Qt/runtime or failing journey. Record the separately required
real Wayland setup-to-export keyboard/picker/focus/clipboard/resize/scaling/
theme/Stop/close walkthrough as PENDING unless actually performed.

## Risks / Trade-offs

- [Resume mistakes a form or candidate for accepted progress] → independent
  saved-artifact assertions with interruption at each acceptance boundary.
- [Create runs twice after asynchronous Save] → one pending root/title payload,
  existing settlement gate and immediate/deferred-path parity tests.
- [Replanning suggests existing drafts were updated] → explicit downstream
  warning, unchanged tree bytes and existing backup/baseline tests.
- [Shared panes have two sets of dirty state] → reuse widgets/presenters;
  advanced and guide paths operate on the same baselines.
- [Session key disappears on restart] → explain expected reentry and preserve
  all independently saved content/history.

## Migration Plan

No migration or wizard storage format; existing projects open normally and
may opt into guidance. Rollback removes the guide, leaving standard saved
artifacts usable by CLI/advanced controls. No new durable architectural choice
beyond the linked ADRs is introduced. Implementation evidence and a fresh
full-parity audit are required; this plan claims no implementation or shipping.
No blocking open questions.
