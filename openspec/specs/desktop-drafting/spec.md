# desktop-drafting Specification

## Purpose

Let authors perform the complete existing draft loop in the native desktop workspace while preserving CLI writing rules, saved branches and explicit control over accepted prose.

## Requirements

### Requirement: Drafting uses shared operations without terminal interaction

The desktop SHALL expose draft actions through Qt-independent shared writing
operations with the CLI as an adapter. Existing prompts, sampling, cleaning,
separators, metadata, histories and file formats SHALL remain compatible; no
terminal prompts, external editors or subprocess automation SHALL be needed.

#### Scenario: CLI and desktop generate the same continuation
- **WHEN** CLI and desktop draft the same synthetic project with identical captured inputs and fake responses
- **THEN** exact prompt, request parameters, cleaned text, node metadata, accepted path and saved scene fields match, normalizing only generated timestamps/paths/IDs
- **AND** the CLI's existing prompts and transcript remain compatible
- **AND** desktop execution never calls terminal input, pager or external editor

### Requirement: Generate captures steering and candidate count

The desktop SHALL enable Generate for a valid writable selected scene with
prerequisites, explain missing prerequisites otherwise, and save the current
steering before making a call. Candidate count SHALL default to writer.swipes
and allow explicit positive N; all candidates SHALL use the captured scene,
head, steering, session length and prompt inputs.

#### Scenario: Unsaved steering drives generation
- **WHEN** the author edits steering and presses Generate with N=2
- **THEN** that steering is saved before the two requests and recorded on each returned candidate
- **AND** candidates are saved after the captured parent while the accepted head stays unchanged

#### Scenario: Steering cannot safely save
- **WHEN** Generate encounters a stale or invalid steering baseline
- **THEN** a recovery message is shown, local steering remains available, and no provider request starts

#### Scenario: Prerequisites are missing
- **WHEN** no writable scene or valid writer preset is available, or required credentials are missing
- **THEN** generation cannot run and the desktop identifies what must be supplied without closing the window

### Requirement: Output is progressive and candidates are complete saved branches

The desktop SHALL show live answer text for every candidate, including
multi-candidate Generate, Reroll selected/all and Add N, without blocking reading.
Unsaved partial output SHALL be visibly provisional, never accepted or stored as
a passage. Complete responses SHALL use existing cleaning, cutoff, end and
absent-mention rules.

#### Scenario: One response streams
- **WHEN** a fake provider pauses between text chunks for N=1
- **THEN** the preview shows successive answer chunks while manuscript navigation still works and before the request completes
- **AND** no partial node exists before the complete response is cleaned and saved

#### Scenario: Multiple candidates complete
- **WHEN** N>1 fake responses interleave chunks and complete under the configured max_parallel
- **THEN** each candidate shows its own answer text before completion with stable preview identities that map to final node identities
- **AND** every saved node retains existing source/model/finish/steer/separator/lore/cast/end/trim/absent metadata

#### Scenario: A stream is retried
- **WHEN** an incomplete attempt fails and the existing retry policy makes another attempt
- **THEN** only the affected candidate's provisional preview resets to a new attempt rather than concatenating failed-attempt fragments into the successful passage
- **AND** other candidates and their saved nodes remain unchanged

#### Scenario: Reroll and add candidates stream
- **WHEN** the writer rerolls selected/all candidates or chooses Add N against the captured batch parent
- **THEN** every new response has its own live provisional preview before completion and completed responses retain existing tray-slot and shortfall behavior
- **AND** original saved branches and accepted head remain unchanged until a separate explicit action

### Requirement: Candidate choice never implicitly accepts or destroys branches

The desktop SHALL offer View, Accept, Reroll selected/all, Add N, Keep branches/
Discard preview and Delete leaf. Accept alone chooses the candidate's ancestor
path as active head; generation/view/reroll/add/discard SHALL NOT do so.

#### Scenario: Accept a candidate
- **WHEN** the author explicitly accepts a saved candidate
- **THEN** its node becomes head, planned status becomes drafting and the active manuscript uses that node's ancestor path
- **AND** the other candidates remain saved branches after reopening

#### Scenario: Reroll and add
- **WHEN** the author rerolls selected candidates or all candidates, then adds N more
- **THEN** returned rerolls replace only their display slots and originals remain branches
- **AND** additions extend the tray and all new nodes share the batch's captured parent

#### Scenario: Fewer rerolls succeed
- **WHEN** fewer complete rerolls return than requested
- **THEN** unmatched slots keep their original text and the author sees the shortfall

#### Scenario: Keep or discard the preview
- **WHEN** the author selects Keep branches or Discard preview without accepting
- **THEN** the tray is dismissed, head is unchanged and complete saved candidates remain accessible in the branch tree
- **AND** deleting prose requires the separately labelled Delete leaf action

### Requirement: Failure preserves accepted prose and earlier complete work

Generation failure, empty cleaned output or cancellation SHALL NOT move head or
save incomplete passages. Earlier accepted text, prior branches and complete
candidates already saved SHALL remain. Errors SHALL restore usable controls
with a readable recovery message.

#### Scenario: Stream fails after displaying text
- **WHEN** a fake provider fails after partial output and exhausts applicable retries
- **THEN** no node is created for that failed response, head and prior branches remain unchanged, and provisional text cannot be accepted
- **AND** a later Generate can run after the worker settles

#### Scenario: A batch partly fails
- **WHEN** some requests return complete responses and others fail or clean to empty
- **THEN** complete successful candidates remain available, failed/empty responses create no nodes and a warning reports the shortfall

### Requirement: Stop and close settle cooperatively

One project operation SHALL run at a time. Stop SHALL be checked at request/
retry, stream-chunk and save boundaries, with blocked waits bounded by existing
configured request timeouts. No thread SHALL be killed. Reading SHALL remain
usable while working/stopping; conflicting writes and project switches SHALL
be unavailable. Close during work SHALL offer Stop and wait / Keep open.

#### Scenario: Stop during streaming
- **WHEN** the author presses Stop after provisional chunks arrive
- **THEN** the UI shows Stopping, partial response text is not saved, no new requests/retries start and head remains unchanged
- **AND** controls return to idle only after all active request work settles

#### Scenario: Stop while the provider is blocked or retrying
- **WHEN** Stop occurs during a blocked request or retry backoff
- **THEN** the request may wait for its configured timeout, backoff is interruptible and cancellation is not retried or swallowed as a candidate failure
- **AND** the UI continues responding without forced thread termination

#### Scenario: Stop reaches a save boundary
- **WHEN** cancellation is observed before a candidate save begins
- **THEN** that candidate is not committed and complete candidates saved before cancellation remain

#### Scenario: Close while working
- **WHEN** the author closes during an operation
- **THEN** Keep open preserves the running window/job, while Stop and wait requests cancellation and closes only after settlement and dirty-editor resolution
- **AND** repeated close/Stop does not start a second job or destroy a running worker

#### Scenario: Read another scene during work
- **WHEN** the author navigates saved scenes/branches while generation is active
- **THEN** reading works but writes/second operations remain disabled
- **AND** progress stays labelled with its original scene/batch and never targets the newly viewed scene

### Requirement: Stale input and unsafe paths cannot silently overwrite work

Every desktop write SHALL validate captured relevant source/destination
baselines and safe project paths. Detected external changes SHALL require reload/
retry rather than overwrite. Refresh SHALL preserve dirty editors and reading
position. Concurrent CLI/GUI writers are unsupported; this is not a lock.

#### Scenario: Input changes before candidate save
- **WHEN** a scene/head/tree, prompt source or relevant lore/config source changes externally while a request is running
- **THEN** the stale write is refused, the change is preserved and the UI offers recovery without accepting the stale response

#### Scenario: A dirty edit becomes stale
- **WHEN** an editor is dirty and its target changes externally or refresh runs
- **THEN** local text and reading state remain available and Save cannot overwrite the changed target without reload/retry

#### Scenario: An unsafe destination is selected
- **WHEN** a mutation would traverse an unsafe scene ID, project escape or symlinked destination under the project
- **THEN** the operation reports the unsafe destination and writes nothing there

### Requirement: Scene controls match draft-loop context inputs

The desktop SHALL expose session passage length, persisted POV/cast, scene-card
view, steering Save/Clear, completion and explicit reopening of done scenes.
Passage length SHALL use the existing max_tokens cap and not silently change
stored project defaults. It SHALL expose Next unfinished, saved head/resume
details and the CLI's prerequisite/earlier-scene/preset warnings.

#### Scenario: Resume the default unfinished scene
- **WHEN** the author chooses Next unfinished in a project with earlier unfinished or unsummarized scenes
- **THEN** the first non-done scene is selected with saved head/steering, active words/target/siblings and earlier-scene warnings
- **AND** ignored writer sampling keys, ignored preset samplers and unsupported sampler-order warnings remain visible when applicable
- **AND** an all-done project explains how to explicitly select a scene instead

#### Scenario: Change length and cast
- **WHEN** the author sets a positive passage length, POV and nonempty cast and inspects/generates the next prompt
- **THEN** length instruction and token cap match CLI `l`, POV/cast use CLI `pov`/`who` semantics and the card shows saved scene fields
- **AND** POV/cast persist in scenes.json while session length does not change the writer default

#### Scenario: Save and clear multiline steering
- **WHEN** the author saves or clears the steering editor, then reopens the scene
- **THEN** the exact saved steering or empty value is restored
- **AND** leaving dirty steering offers Save/Discard/Cancel

#### Scenario: Mark done or decline model-signalled completion
- **WHEN** the author presses Mark done or accepts a scene-end candidate and confirms Mark done
- **THEN** status becomes done and the desktop explains that continuity update is a separate step, without running it
- **AND** declining the model-end confirmation leaves the post-accept scene status unchanged, normally drafting, without implicitly resetting an explicitly reopened done scene

#### Scenario: Reopen a done scene
- **WHEN** the author explicitly selects a done scene for drafting
- **THEN** its saved head and branches are available for further draft actions just as with CLI --scene

### Requirement: Context inspection shows exact next-call content

The desktop SHALL expose CLI `c`'s budget, sampler, notes and injected-lore
inspection and CLI `cp`'s exact prompt dump without making a provider call.
It SHALL preserve over-budget refusal and existing warnings.

#### Scenario: Inspect and dump a prompt
- **WHEN** the author opens Context and Exact prompt for current captured inputs and chooses Save last_prompt.txt
- **THEN** displayed budget parts/ceiling/completion allowance, sent/extra/ignored sampler information, injected lore and exact prompt agree with CLI c/cp
- **AND** last_prompt.txt has the exact prompt bytes and no provider call occurs

#### Scenario: A prompt exceeds budget
- **WHEN** the same prepared prompt exceeds the existing context limit
- **THEN** generation refuses the call and shows the budget report and notes rather than silently changing sampling or dropping user content differently from the CLI

### Requirement: Manual writing and head edits preserve existing history semantics

The desktop SHALL provide built-in plain-text Save/Cancel editors for new
passages and the head passage, with existing whitespace, history and diff rules.

#### Scenario: Append a manual passage
- **WHEN** the author saves a nonempty manual passage
- **THEN** a source=user paragraph node is appended after head, becomes head and changes planned status to drafting
- **AND** cancelling or saving empty input makes no passage change

#### Scenario: Work without provider credentials
- **WHEN** a valid planned project is opened without provider credentials and the author writes manually or inspects context
- **THEN** those no-call actions remain usable while generation explains the missing credential prerequisite

#### Scenario: Edit the head
- **WHEN** the author saves a changed nonempty head edit
- **THEN** prior text/time/by=user-edit is recorded in history, continuation-leading whitespace is preserved and the diff is shown
- **AND** cancelling, empty or unchanged input leaves the saved node untouched

### Requirement: Branch controls expose every node and explicit path mutations

The desktop SHALL show all saved nodes with head/active-path markers, parent/
children, text, metadata/history and end/trim/absent warnings. It SHALL offer
rewind, jump/use-as-head, eligible leaf deletion, scene text with node markers
and a configurable tail view defaulting to 600 characters.

#### Scenario: Navigate without accepting
- **WHEN** the author views an inactive candidate/node or expands its metadata/history
- **THEN** its full text and saved metadata are readable and head is unchanged
- **AND** scene text with node markers and Tail N match CLI v/tail for the active path

#### Scenario: Rewind and switch branches
- **WHEN** the author rewinds and then chooses Jump/Use as head on another node
- **THEN** rewind first moves head to its parent without deleting text, and jump explicitly switches the accepted path to the chosen node

#### Scenario: Delete an eligible or ineligible node
- **WHEN** the author requests Delete leaf for a leaf, including a head leaf, or a node with children
- **THEN** a leaf is deleted and a deleted head moves to its parent, while a node with children is refused without tree changes

### Requirement: Lore controls preserve existing registry and parsing rules

The desktop SHALL list all lorebooks with on/off, kind, character/aliases, entry
count and POV/present role. It SHALL offer individual/multi toggles, All on/off,
Character + name, aliases, World and file-picker import of supported JSON/PNG
World Info/character cards using existing parsing and classification, without
file-format changes.

#### Scenario: Toggle and classify lore
- **WHEN** the author toggles books individually/together, uses All on/off, sets Character + name/aliases and switches another book to World
- **THEN** lorebooks.json matches equivalent CLI lb actions and the next prompt's matching/injected lore uses those values
- **AND** every discovered book, including disabled/empty books, remains listed with its current role and entry count

#### Scenario: Import validated files
- **WHEN** the author selects valid World Info JSON or V1/V2/V3 character JSON/PNG files in the desktop picker
- **THEN** unchanged file bytes are copied into safe lorebooks destinations, existing parsing/discovery sets default metadata and the books appear without terminal interaction

#### Scenario: Cancel or reject an import
- **WHEN** the picker is cancelled or an input is unreadable/invalid under existing parsing
- **THEN** no invalid destination or registry update is saved and parsing errors/warnings are displayed

#### Scenario: Import filename collides
- **WHEN** an import destination already exists
- **THEN** Replace/Cancel names the destination, Cancel leaves it unchanged and Replace requires confirmation plus unchanged source/destination baselines
- **AND** existing registry metadata for that filename is preserved

### Requirement: Draft help and leaving the loop need no terminal

The desktop SHALL expose draft action help and Leave draft without closing the
reader or losing saved branches; unsaved editors SHALL be resolved explicitly.

#### Scenario: Consult help and leave
- **WHEN** the author opens draft help, then leaves the active draft session
- **THEN** available draft and candidate actions are described, dirty editors offer Save/Discard/Cancel and saved prose remains readable

### Requirement: Offline checks cover operation and worker button flows

The existing scripts/check.sh SHALL run headless core/CLI parity tests and
offscreen Qt subprocess button-flow tests through the worker/queued-signal
seams, without live network or weakened guards. Real Wayland acceptance SHALL
remain separately recorded rather than inferred from offscreen tests.

#### Scenario: Run the repository checks
- **WHEN** scripts/check.sh runs with the declared dependencies installed and network access guarded
- **THEN** new generation/accept/reroll/edit/branch/lore/context flows and Stop/failure/stale/close tests run alongside existing checks and pass
- **AND** missing Qt or a failed widget case fails rather than silently skips the coverage

#### Scenario: Demonstrate native desktop behavior separately
- **WHEN** the implemented workspace undergoes owner desktop acceptance
- **THEN** its Wayland platform/compositor/runtime, generation/Stop/close, file-picker, keyboard/clipboard and available scaling/theme results are recorded separately
- **AND** this drafting acceptance is not described as full GUI parity or authorization to ship
