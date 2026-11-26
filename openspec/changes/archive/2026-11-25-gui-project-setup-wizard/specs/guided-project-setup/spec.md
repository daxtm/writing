## Purpose

Help first-time writers create and resume a project through explicit planning choices until saved scenes are ready for drafting.

## ADDED Requirements

### Requirement: Create opens a reopenable ordered setup guide
Create SHALL enter location/title/defaults, credentials, local bible answers,
outline generate/choose, scene cards generate/edit/accept, then first unfinished
scene. Successful initialization SHALL continue in the guide. Plan SHALL offer
Resume setup for incomplete projects and Reopen setup for existing projects.
Open alone SHALL stay read-only and not force the guide.

#### Scenario: Create from a missing directory
- **WHEN** the writer launches for a missing directory, chooses Create, supplies location/title and confirms Create project
- **THEN** complete shared defaults including the preset are initialized once without calls and the guide continues to credentials
- **AND** the title is saved, defaults are described as local/nonsecret and no external preset path is needed

#### Scenario: Cancel, deferred Create or partial failure
- **WHEN** the location is cancelled, old-project dirty Save fails/cancels, or initialization stops/fails after partial work
- **THEN** the wizard does not claim successful creation or bind the wrong project, prior usable work remains and partial paths/retry guidance are shown
- **AND** retry only fills missing paths and never resets existing content

#### Scenario: Reopen without forcing guidance
- **WHEN** the writer opens an existing project and chooses Resume setup or Reopen setup from Plan
- **THEN** the guide displays saved planning progress and the earliest incomplete step
- **AND** opening or reopening performs no initialization, provider request or automatic content acceptance

### Requirement: Back and Next never perform paid or acceptance actions
The guide SHALL show Back, Next and Save and resume later with step purpose,
missing inputs, destination and primary action. Navigation SHALL NOT generate,
choose, accept or discard implicitly. Only action-specific prerequisites SHALL
block a dependent action; the writer SHALL retain manual/advanced paths.

#### Scenario: Navigate freely without hidden side effects
- **WHEN** the writer moves Back/Next over saved or incomplete steps or leaves for Advanced planning
- **THEN** no generation or acceptance runs, incomplete dependencies are explained and saved work remains unchanged
- **AND** credentials may be skipped for local/manual work and the writer can return to the guide

### Requirement: Credential setup reuses explicit session and project choices
The credentials step SHALL offer the same masked input, Use for this session,
Save/Replace/Clear, plaintext warning, source/status and explicit Test connection
as Setup. It SHALL never reveal/prefill an existing key or require project
persistence to continue.

#### Scenario: Session-only setup and reopen
- **WHEN** the writer activates a synthetic session key, proceeds to planning, leaves/closes and reopens the project
- **THEN** generation used that window's session credential without persistence and reopened credentials reflect only saved project/environment availability
- **AND** saved bible/outline/scene progress is retained even when the session key must be entered again

### Requirement: Bible questions compose locally and require section acceptance
The bible step SHALL present existing fixed forms, saved answers/history,
local section preview, Edit answers, Accept, Skip and direct-edit options.
Saving answers SHALL NOT accept sections; acceptance SHALL retain existing
composition, section order and backup semantics. No AI bible call SHALL exist.

#### Scenario: Save, interrupt and accept local answers
- **WHEN** the writer saves a multiline section form, leaves/reopens and explicitly accepts its composed preview
- **THEN** the form/history is restored and only Accept changes that section in `bible.md`
- **AND** no provider request occurs and skipped/template sections remain visibly incomplete without blocking unrelated local work

### Requirement: Outline and scene generation remain author-controlled
Outline and scene steps SHALL label Generate/Reroll/Regenerate as provider
actions that may incur cost and require explicit invocation. Every answer/
candidate SHALL stream into a provisional preview; only completed choices/
valid cards SHALL be selectable for acceptance under existing rules.

#### Scenario: Choose an outline after live competing previews
- **WHEN** the writer explicitly generates two outlines and the fake streams pause after first answer chunks
- **THEN** both owning previews show text while busy and Next cannot choose a provisional result
- **AND** after completion only explicit Choose changes `outline.md`, retains candidates/history and does not generate scenes

#### Scenario: Generate, edit and accept scene cards
- **WHEN** the writer explicitly generates cards from the saved outline, sees raw streamed JSON, edits completed valid cards and presses Accept
- **THEN** only validated completed cards replace `scenes.json` with existing normalization and scene/history rules
- **AND** malformed completed output exposes existing raw correction/regeneration guidance and cannot be accepted

### Requirement: Readiness and resume use saved artifacts not wizard state
Resume SHALL derive the earliest incomplete step from valid saved project
configuration, accepted nonplaceholder bible content, saved outline, valid
nonempty scene cards and existing answer/history inputs. Unsaved answers,
candidates and provisional responses SHALL NOT count as accepted progress.
No wizard-only authoritative project document SHALL be created.

#### Scenario: Resume after interrupted output or saved answers only
- **WHEN** the window is reopened after saving bible answers without Accept, generating an unchosen outline or stopping scene generation
- **THEN** the guide restores saved forms/candidate history and identifies the missing accepted artifact instead of advancing from an old page number
- **AND** no partial result is treated as ready or silently regenerated

#### Scenario: Read external saved changes truthfully
- **WHEN** accepted planning artifacts are edited externally, removed or become malformed while the guide is closed
- **THEN** reopened readiness reflects those saved sources with actionable errors rather than cached complete flags

### Requirement: Dirty changes resolve before destructive transitions
Back/Next, step replacement, leave/reopen, project switch and close SHALL preserve
dirty forms or offer Save/Discard/Cancel. Failed/stale Save SHALL prevent
destructive transitions; Save SHALL use existing input/history semantics and
SHALL NOT implicitly accept generated content.

#### Scenario: Resolve dirty input
- **WHEN** bible/notes/outline/card edits would be replaced and the writer chooses Cancel, Save or Discard
- **THEN** Cancel retains the current step and text, successful Save persists only the intended edits and Discard reloads saved state
- **AND** failed/stale Save retains edits and blocks the transition; no choice triggers the next paid action

### Requirement: Replanning warns about downstream effects and retains history
Replacing a saved outline SHALL explain that existing scenes/drafts are not
automatically regenerated or deleted. Scene regeneration/replacement SHALL use
existing force/replace confirmations with current baselines, naming downstream
effects and preserving candidate/backups, existing trees and accepted prose.

#### Scenario: Replace planning after drafting
- **WHEN** the writer revisits outline/scenes after saved scenes or trees exist
- **THEN** outline replacement warns about unchanged downstream work, and scene force/replace confirmations identify `scenes.json` and retained trees before the respective provider/write actions
- **AND** declining or stale consent changes nothing; confirmed actions retain existing outline/scene backups and tree bytes without claiming downstream synchronization

### Requirement: Finishing setup opens saved writing rather than generating prose
Enter Write SHALL select the first saved scene not marked done, loading saved
head/steering and prerequisites. It SHALL NOT generate, accept, mark done or
update continuity. With all scenes done it SHALL explain deliberate selection.

#### Scenario: Begin writing or revisit a complete plan
- **WHEN** valid saved cards exist and the writer chooses Enter Write
- **THEN** Write opens at the first unfinished scene with the existing draft controls, or shows an all-done explanation with explicit scene selection
- **AND** tree/head/status/continuity files remain unchanged and no provider call occurs

### Requirement: The full guided journey is offline-checkable and accessible
Checks SHALL run an offscreen interrupted/reopened setup-through-export journey
using synthetic credentials and paused fake streams, plus keyboard/focus/labels,
empty/error and resize/palette cases. One-worker Stop/close and existing parity
SHALL remain intact. Real Wayland acceptance SHALL stay separately PENDING.

#### Scenario: First-time journey without terminal knowledge
- **WHEN** `./scripts/check.sh` runs the registered guided journey from a missing directory
- **THEN** it exercises creation, credentials, local bible acceptance, streamed outline/cards, interrupted resume, Write generation/Accept, continuity/review/revision and picked export without terminal/config/preset editing
- **AND** tests assert intermediate preview text before release, saved results and no implicit paid calls; failing cases or missing Qt fail checks

#### Scenario: Separate desktop acceptance
- **WHEN** offscreen checks pass but an owner Wayland walkthrough has not run
- **THEN** the record remains PENDING for native keyboard/focus, file pickers, clipboard, resize/scaling/themes and Stop/close
- **AND** no whole-workspace completion or shipping is claimed
