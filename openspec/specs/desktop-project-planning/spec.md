# desktop-project-planning Specification

## Purpose

Let writers create, configure and plan an existing-format fiction project through native desktop controls until its saved scene cards are ready for the existing drafting workspace.

## Requirements

### Requirement: Create and Open work without a prepared project
The GUI SHALL offer desktop Create/Open directory selection even when launched
with a missing directory, missing configuration or no scenes. Explicit Create
SHALL use existing initialization contents and create-missing-only semantics.
Open SHALL read without initializing or requesting the provider.

#### Scenario: Create from an empty location
- **WHEN** the writer launches `gui DIR` for a missing directory and confirms a location through Create
- **THEN** the five default project files and seven initialization directories are created with the same contents as CLI init
- **AND** setup controls remain usable with an empty scene list, without a terminal question or provider call

#### Scenario: Repeated initialization and cancelled selection
- **WHEN** Create targets an existing partially initialized project or the directory dialog is cancelled
- **THEN** existing files remain unchanged and only missing initialization paths are created on confirmed Create
- **AND** cancelling creates nothing and leaves the current project selected

#### Scenario: Open or fail safely
- **WHEN** the writer opens an existing valid project, or selects a directory with missing, malformed or unsafe configuration
- **THEN** a valid project displays its existing content without changes or calls
- **AND** an invalid selection reports an actionable error without resetting files or replacing the currently usable project

### Requirement: Preset import preserves master-export validation and no-overwrite behavior
The GUI SHALL import an explicitly picked SillyTavern master-export JSON using
the existing required keys and unchanged source bytes. Import SHALL never
overwrite `writer_preset.json`.

#### Scenario: Import a valid preset
- **WHEN** the writer selects a valid master export containing instruct, context, sysprompt and preset and the destination is absent
- **THEN** its original bytes are copied to `writer_preset.json` and readiness is refreshed using the existing preset/override behavior

#### Scenario: Reject invalid input or destination collision
- **WHEN** the picker is cancelled, the source is unreadable/invalid/missing a required key, or `writer_preset.json` already exists
- **THEN** cancellation makes no change, invalid input displays a validation error, and a collision displays a not-overwritten warning
- **AND** no existing preset or chosen external source is modified

### Requirement: Settings edit supported nonsecret fields only
The GUI SHALL provide validated Save/Cancel forms for supported nonsecret
project, role/model, sampler, writer, budget and review-configuration settings.
It SHALL preserve unknown/unedited fields, refresh prerequisites without a
provider call, and offer no raw configuration or key editor.

#### Scenario: Supported configuration controls
- **WHEN** the writer opens Settings
- **THEN** controls cover title/target, provider base/environment name, context fallback/safety/prompt/section budgets, token-estimation ratio, concurrency/timeout, existing role models and supported chat samplers/thinking, writer preset/swipes/passage/user/lore, summary sizing, banned phrases and ngrams
- **AND** preset overrides expose existing consumed temperature/probability/top-k/penalty/output/context/DRY fields rather than new inert options

#### Scenario: Save and reopen nonsecret settings
- **WHEN** the writer changes supported models, budgets, concurrency and writer preset overrides and presses Save
- **THEN** `project.json` contains those values in the existing schema, unknown fields remain intact and reopening shows the saved settings
- **AND** no limits fetch, generation or implicit next command runs

#### Scenario: Refuse invalid configuration
- **WHEN** a form contains a blank model, invalid environment name, nonfinite number, boolean integer, nonpositive concurrency, invalid probability, malformed list or unsupported enum
- **THEN** Save identifies the invalid fields and leaves saved configuration unchanged
- **AND** the writer's unsaved entries remain available for correction

#### Scenario: Cancel settings
- **WHEN** the writer cancels a dirty settings form
- **THEN** configuration remains unchanged and subsequent operations use saved values

### Requirement: Credential presentation never reveals a key
The GUI SHALL show the configured environment variable name and missing/available
status, and only boolean effective credential availability using existing Api
precedence. It SHALL NOT render, accept, copy or persist a new credential value,
expose headers/raw configuration, or leak a credential in results/errors.
Existing inline keys SHALL be preserved opaquely by nonsecret saves.

#### Scenario: Environment and legacy inline credentials
- **WHEN** a project uses an environment key or an existing inline key and the writer views or saves Settings
- **THEN** the GUI shows the environment name/status and effective availability without the key value
- **AND** no new key is stored and an existing inline field is neither displayed, changed nor migrated

#### Scenario: Missing credentials and an echoed secret
- **WHEN** credentials are absent or a fake provider failure body includes a sentinel credential
- **THEN** provider controls explain missing credentials or show a sanitized failure, without exposing the sentinel anywhere in GUI text/events
- **AND** local bible/settings/card editing remains available when its own file prerequisites are valid

### Requirement: Limits are fetched only by explicit action
Fetch limits SHALL use the shared Api and existing plan/model lookup, limit
extraction and `limits.json` shape on the one worker. It SHALL display fetched
time, plan context/concurrency and role/model context, completion, availability,
not-found and error results, sanitized for display.

#### Scenario: Fetch configured model limits
- **WHEN** the writer explicitly requests Fetch limits with saved valid configuration and credentials
- **THEN** the provider receives the existing plan request and one lookup per distinct configured model
- **AND** complete results are displayed and saved in CLI-compatible `limits.json`, including model-404 `found:false` and unavailable-on-plan results

#### Scenario: No implicit requests or destructive failure
- **WHEN** the writer creates/opens a project or saves settings, or an explicit fetch fails or is stopped
- **THEN** creation/open/save makes no provider request and failed/stopped fetch leaves the previous `limits.json` unchanged
- **AND** the GUI explains the result and restores usable controls after worker settlement

### Requirement: Bible answering uses existing questions and explicit section acceptance
The GUI SHALL present the existing ordered sections and fixed question/character
forms with multiline editing, saved answers, preview, Edit answers, Accept,
Skip and Leave choices. It SHALL reuse existing compose/split/join rules,
answer input/history paths, session backups and token-budget warnings without
launching an external editor or terminal prompt.

#### Scenario: Answer and accept a section
- **WHEN** the writer begins a bible session, fills a form and saves answers
- **THEN** an existing bible is backed up once for that session, the exact form is saved in the existing input/history locations, and the composed section is previewed
- **AND** only explicit Accept updates that section in `bible.md`, retaining preamble, section order and other section content under existing join normalization

#### Scenario: Reopen answers, skip or leave
- **WHEN** the writer reopens a section with saved answers, edits its preview, skips it or leaves without accepting
- **THEN** saved forms are reused and unaccepted content does not replace `bible.md`
- **AND** previously accepted sections and explicitly saved answers/history remain intact

#### Scenario: Characters and custom text
- **WHEN** the writer opens Characters or a custom section containing existing nonplaceholder text
- **THEN** Characters uses existing lore-derived names/fields and extra-character/notes questions, while custom sections use the existing generic question
- **AND** current text is visible and is not silently inferred into blank answers or overwritten

#### Scenario: Direct section editing and history
- **WHEN** the writer directly edits an existing section and saves or views bible/answer history
- **THEN** a backed-up save changes only the chosen section through existing composition boundaries, and safe history files are viewable without mutation
- **AND** a no-section/malformed bible reports an error instead of resetting content, and over-budget text shows the existing warning

### Requirement: Outline generation keeps competing candidates and author control
The GUI SHALL expose saved notes, N>=1, Generate, Reroll same notes, edit-notes
reroll, full candidate viewing, selection, built-in body editing and Cancel/Leave.
Generation SHALL run the shared planner messages/sampling and existing tag
extraction on the worker. Rerolls SHALL append candidates, not delete history.

#### Scenario: Generate with notes and reroll
- **WHEN** the writer saves multiline notes, requests two outline candidates and rerolls with unchanged or edited notes
- **THEN** notes and their history use existing paths and the provider receives the same filtered notes, bible, target, planner prompt and parameters as the corresponding CLI flow
- **AND** complete candidates are saved using existing naming/notes-comment conventions and listed alongside earlier candidates without changing `outline.md`

#### Scenario: Choose or edit with history
- **WHEN** the writer chooses a candidate or saves an edited working outline body
- **THEN** `outline.md` contains the chosen/edited body without its leading candidate notes comment, and any previous outline is backed up in `outlines/outline_prev_<stamp>.md`
- **AND** the original candidate file is retained and no scene generation runs automatically

#### Scenario: Warnings, shortfall and reopen
- **WHEN** a response lacks tags, is cut off, has a partial batch failure or no candidates, or the writer reopens saved candidate history
- **THEN** the existing extraction/finish/shortfall warnings or errors are visible, complete saved candidates remain viewable, and the selected outline is unchanged without explicit Save
- **AND** reopened historical choices are identified as history and bound to current inputs only by a new explicit selection

### Requirement: Scene generation previews validated cards before saving
The GUI SHALL generate scene cards from a saved outline using shared planner
messages/parsing/normalization, display cards and total words, allow built-in
editing, and offer View, Regenerate, Accept and Cancel. Invalid card data SHALL
produce recoverable field/parse errors rather than an unhandled exception.

#### Scenario: Generate, inspect, edit and accept
- **WHEN** the writer generates cards, views them, edits valid fields and explicitly accepts
- **THEN** the saved `scenes.json` uses existing ordering, generated IDs, defaults, planned status, state_updated flag and serialization, including CLI-compatible missing-field normalization
- **AND** the existing scene sidebar/draft readiness refreshes without a terminal editor or automatic prose generation

#### Scenario: Invalid response or editor values
- **WHEN** generated output is not a valid object array or an edited card has invalid lists, unsafe IDs, nonintegral/negative counts or wrong field types
- **THEN** Accept is refused with actionable errors and the previous `scenes.json` is unchanged
- **AND** unparseable provider output is saved at the existing raw-output path for inspection and Regenerate/Cancel, while unsaved edits are retained for correction

#### Scenario: Valid defaults and advisory word targets
- **WHEN** generated cards omit fields allowed by existing normalization or their valid target-word total differs from the project target
- **THEN** existing defaults are used and missing descriptions/zero words/total mismatch are warnings, not invented content or an exact-total acceptance gate

### Requirement: Scene replacement requires explicit informed consent and keeps trees
The GUI SHALL mirror `scenes --force` protection for drafted cards or any tree
files, and SHALL confirm replacement of any nonempty scene list before saving.
Accepted replacement SHALL preserve existing backup behavior and never delete
trees. Declined consent SHALL not be reused for a later attempt.

#### Scenario: Force protection before regeneration
- **WHEN** any existing card is not planned or any tree JSON exists and the writer requests regeneration
- **THEN** the GUI names `scenes.json`, explains that trees are retained and requires force-equivalent confirmation before calling the provider
- **AND** declining runs no request and changes no scene/tree files

#### Scenario: Replace planned or drafted scenes
- **WHEN** a valid new preview would replace a nonempty scene list and the writer confirms Replace against the still-current source baseline
- **THEN** the previous list is copied to `outlines/scenes_prev_<stamp>.json` and the new list is saved
- **AND** all tree bytes remain unchanged and retained trees remain readable

#### Scenario: Cancel or stale consent
- **WHEN** the writer cancels Replace or the scenes/tree membership changes after confirmation
- **THEN** no replacement is committed and stale consent cannot authorize overwriting the changed data

### Requirement: Existing scene cards can be edited without resetting drafting
The GUI SHALL edit supported descriptive/planning fields of saved cards while
preserving IDs, order, status, state_updated, unknown fields and all trees.
Changed saves SHALL use scene backup/validation/stale guards; unchanged saves
SHALL be no-ops.

#### Scenario: Edit a drafted card
- **WHEN** the writer changes a saved card's title, chapter, POV/cast, setting, goal/conflict/outcome/beats, notes or target words and saves
- **THEN** valid edits are saved with a previous-scenes backup without changing scene identity/order/status/state flags or any tree
- **AND** existing draft controls consume the saved card and dirty prose/steering is not silently discarded

### Requirement: Prerequisites and dirty editors are explained
Disabled planning actions SHALL explain missing prerequisites and recovery.
Local planning SHALL not require a selected draft scene, writer preset, limits
or credentials unless that action actually consumes them. Project changes,
editor replacement and close SHALL resolve unsaved input with Save/Discard/Cancel.

#### Scenario: From bible to scene-ready draft
- **WHEN** no scenes exist, the bible/outline is missing or credentials/preset are absent
- **THEN** Create/Open and valid local edits remain usable, outline generation explains its bible/model/credential needs, scene generation explains its saved-outline/model/credential needs, and drafting explains its own prerequisites
- **AND** planner calls are not gated by a writer preset or selected scene, nor automatically chained

#### Scenario: Dirty form during navigation
- **WHEN** refresh, navigation, project Open/Create or close would replace unsaved settings, bible, notes, outline, card or existing draft editor contents
- **THEN** dirty text is preserved or Save/Discard/Cancel is offered, with Cancel or failed/stale Save preventing the destructive transition

### Requirement: Planning uses one responsive and cancellable operation lifecycle
The GUI SHALL run planning through the existing single worker, preserve readable
views, disable conflicting writes/project switching, and deliver queued progress/
results to GUI-thread widgets. Stop SHALL be cooperative at request, retry,
chunk and save boundaries; close SHALL offer Stop and wait / Keep open.

#### Scenario: Work, Stop and close
- **WHEN** a fake planner or limits request is held at a controlled boundary and the writer reads, attempts conflicting work, presses Stop or closes
- **THEN** reading remains responsive, conflicting work is refused with a reason, Stop schedules no further request/retry and partial responses cannot be accepted
- **AND** close waits without freezing until the worker and bounded internal requests settle, then resolves dirty editors

#### Scenario: Retain saved work and recover from failure
- **WHEN** a planning operation stops/fails after a form or complete candidate has already been saved
- **THEN** saved work remains, the accepted bible/outline/scenes are not replaced by partial previews, and the GUI reports what actually saved
- **AND** controls recover exactly once after settlement and late operation signals cannot update a different project or preview

### Requirement: Stale and unsafe inputs never authorize an overwrite
Planning SHALL capture relevant exact source/destination bytes or absence and
directory membership, carry baselines through preview/accept, and refuse detected
external changes before writes/backups. It SHALL retain existing canonical-root,
safe-source/no-symlink policies, including temporary and history targets.
This SHALL NOT claim simultaneous CLI/GUI writers are supported or saves are
multi-file transactions.

#### Scenario: Source changes between generation and acceptance
- **WHEN** the bible, configuration, outline, notes, selected candidate, scene list or other consumed source changes externally after capture
- **THEN** a dependent save/accept refuses the stale result without overwriting changed files, retains local edits and explains Reload/retry

#### Scenario: Unsafe destination or changed import
- **WHEN** a source/backup/destination/temp path below the canonical root is symlinked or escaping, or a selected import source changes before commit
- **THEN** the operation refuses unsafe/stale persistence with a sanitized error and leaves existing files intact

### Requirement: Offline parity and GUI acceptance are check-discoverable
The existing check entry point SHALL run headless planning/model validation,
fake-provider CLI/GUI prompt/file/history/transcript parity where applicable,
and offscreen Qt button flows with no network, private data, silent skips or
weakened guards. Real native Wayland acceptance SHALL be recorded separately.

#### Scenario: Run the complete offline suite
- **WHEN** `./scripts/check.sh` runs with provisioned dependencies and blocked external network
- **THEN** syntax, CLI help, headless planning tests and actual offscreen Create-to-scene worker/button flows run and pass, including failure/cancel/stale/secret/replace coverage
- **AND** equivalent fixed-input CLI/GUI flows preserve prompt/provider-body and saved file/history bytes and existing applicable CLI transcripts

#### Scenario: Offscreen is not compositor evidence
- **WHEN** offscreen coverage passes without a real Wayland desktop run
- **THEN** the planning acceptance record remains explicitly PENDING for Wayland pickers, forms, keyboard/focus/clipboard, available scaling/themes and planner Stop/close
- **AND** neither whole-workspace completion nor shipping is claimed
