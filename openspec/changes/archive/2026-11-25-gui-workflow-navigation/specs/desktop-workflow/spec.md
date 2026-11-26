## Purpose

Guide writers through planning, writing, review and export in focused desktop stages while keeping every existing action discoverable.

## ADDED Requirements

### Requirement: Four primary stages replace the equal-priority tab wall
The window SHALL offer Plan, Write, Review and Export in that order as primary
navigation, with project overview available from Plan. Each stage SHALL explain
its purpose, required inputs, output location and one primary next action.
Advanced tools SHALL use labelled secondary panels, not fifteen primary tabs.

#### Scenario: New and existing project layouts
- **WHEN** the writer opens either an empty initialized project or a populated project
- **THEN** four labelled primary stages are visible in order and the selected stage presents its purpose, inputs, output and next action
- **AND** the window does not present the former fifteen tools as equal-priority primary tabs

### Requirement: Overview readiness comes from saved writing artifacts
Overview SHALL show project identity, saved planning/draft progress, credential
source/status and actionable missing/invalid prerequisites without secrets,
writes or provider calls. Unsaved forms and provisional generated text SHALL
not count as completed work. Warnings SHALL link to relevant recovery controls.

#### Scenario: Distinguish initialized templates from saved plans
- **WHEN** a new project has template bible/outline files but no accepted story content or scene cards
- **THEN** overview identifies incomplete planning rather than treating file existence as readiness and offers the appropriate local next action
- **AND** entering or generating an unaccepted preview does not mark that step complete

#### Scenario: Saved progress and malformed sources
- **WHEN** saved bible/outline/cards, active heads or summary freshness change, or a saved source becomes unreadable/invalid
- **THEN** refreshed overview reflects saved facts or an explicit source error with recovery, never invented ready status
- **AND** browsing/refresh preserves project bytes and never fetches limits or generates output

### Requirement: Draft controls are contextual to Write
Draft steering, candidate count and draft Generate SHALL appear only in Write
with their selected scene, reading/candidate context and prerequisite reasons.
Other stages SHALL expose only their own generation controls. Global operation
status and Stop SHALL remain reachable from every stage during work.

#### Scenario: Move between stages
- **WHEN** the writer visits Plan, Write, Review and Export
- **THEN** draft steering/Generate/count are visible only in Write, while outline/scenes and review generation stay in their owning stages
- **AND** stage changes alone make no call, save or acceptance

#### Scenario: Leave Write during a held request
- **WHEN** a draft request is paused and the writer browses Review or Export
- **THEN** originating scene/candidate progress and Stop remain available and returning to Write shows its live previews
- **AND** conflicting generation/write/export actions remain disabled until settlement

### Requirement: Every existing action remains discoverable
All existing CLI-equivalent GUI actions SHALL remain reachable through labelled
stage controls or secondary panels with unchanged writing rules. The parity
map SHALL identify each action's new route, control and executed regression
case; hidden or removed actions SHALL be treated as gaps, not parity.

#### Scenario: Advanced-action audit
- **WHEN** the offline parity journey follows every row of the existing full-parity coverage map through stage and secondary-panel controls
- **THEN** it reaches planning/settings/limits, all draft/tray/manual/branch/context/lore actions, continuity/compression, reports/checks/revision/status and destination-picked export
- **AND** equivalent saved results/prompts and existing CLI transcripts remain unchanged

### Requirement: Review and Export are deliberate not gated pipelines
The writer SHALL be able to enter Review or Export deliberately with advisory
readiness warnings. These stages SHALL retain existing action-specific
prerequisites without new mandatory review gates or automatic generation,
acceptance, status mutation or export.

#### Scenario: Export without completing optional review
- **WHEN** a project has saved prose but missing/stale summaries or no critique and the writer enters Export
- **THEN** concerns are explained but the existing valid destination-picked export remains usable
- **AND** no review request or source save starts unless explicitly chosen

### Requirement: Navigation preserves edits and reading state
Stage/panel changes and refresh SHALL retain selection, cursor/scroll,
provisional previews and dirty forms when possible. Any transition that would
replace edits SHALL offer Save/Discard/Cancel; Cancel or failed/stale Save
SHALL prevent the transition. Saved branches/history SHALL remain intact.

#### Scenario: Dirty stage change and refresh
- **WHEN** a dirty steering, settings, bible, outline, card, report or revision editor would be replaced by navigation or refresh
- **THEN** text remains available or Save/Discard/Cancel is offered and Cancel/failed Save leaves the prior context selected
- **AND** successful Save uses the existing operation, never accepts a different preview or starts a paid next step

### Requirement: Focused navigation is usable without pointer or fixed theme
Stages and secondary tools SHALL have meaningful labels, predictable keyboard
focus, visible focus indication and recoverable empty/error states. Layouts
SHALL remain operable under resizing, larger prose/font sizes, supported
scaling and light/dark system palettes without obscuring primary actions.

#### Scenario: Offscreen keyboard and presentation checks
- **WHEN** widget tests navigate stages/panels by keyboard, resize the window and apply larger fonts and contrasting system palettes
- **THEN** labelled controls remain reachable in logical order, focus moves to the destination heading/primary control and text/actions remain readable with scrolling where necessary
- **AND** Enter in multiline editors inserts text rather than triggering Generate, Save or acceptance

### Requirement: Acceptance distinguishes offline parity from real Wayland
Project checks SHALL run registered offscreen stage/parity/presentation
regressions and existing source/frozen coverage without skips or live calls.
Real Wayland keyboard/picker/resize/scaling/theme/Stop/close results SHALL be
recorded separately and remain PENDING if unavailable.

#### Scenario: Checks and desktop evidence
- **WHEN** `./scripts/check.sh` runs before real desktop acceptance is available
- **THEN** the stage journey and parity regressions execute and pass, with a failed or unregistered case failing checks
- **AND** the evidence still marks native Wayland acceptance PENDING and makes no whole-workspace completion or shipping claim
