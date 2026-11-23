## Purpose

Let writers maintain continuity, review and revise saved scenes, inspect project status and export their manuscript entirely through existing-format desktop controls.

## ADDED Requirements

### Requirement: Desktop review preserves the CLI writing contract
The desktop SHALL expose update-state, compress, critique, check, revise,
status and export without terminal input, pagers or external editors. CLI and
desktop SHALL share writing behavior and preserve existing prompts, samplers,
files, reports, diffs and histories; existing CLI transcripts SHALL remain
unchanged for equivalent choices.

#### Scenario: Equivalent CLI and button journeys
- **WHEN** CLI and desktop run equivalent choices against identical synthetic projects and fake responses at a fixed clock
- **THEN** request messages/parameters, saved files/history, report text and diff content match byte-for-byte after normalizing only temporary roots and generated timestamps
- **AND** desktop actions never invoke terminal helpers or an external editor, and existing CLI prompts/transcripts remain identical

#### Scenario: No implicit pipeline
- **WHEN** the writer opens a review pane, changes selection, refreshes, accepts continuity or finishes revision
- **THEN** no provider call, report save, compression, next command or export starts without its own explicit action
- **AND** missing provider credentials disable paid actions with recovery guidance, not local checks, editing, status or export

### Requirement: Update-state previews require explicit acceptance
The desktop SHALL support the CLI's default waiting-done scene and explicit
scene selection, summary-only, detailed/brief previews and state diff/full-state
preview. Edit, Regenerate, Accept and Quit SHALL remain separate choices.
Only Accept SHALL commit summaries, state or scene flags.

#### Scenario: Accept a completed scene's continuity
- **WHEN** the writer generates update-state for a completed scene containing active text
- **THEN** detailed and brief summaries and the proposed full state with a `state.md` to `updated` line diff appear without changing continuity files
- **AND** Accept backs up the prior state as `state_history/before_<scene>_<stamp>.md`, writes the proposed state with existing newline semantics, marks `state_updated` true, and saves summary text, updated time and active-text hash in `summaries.json`

#### Scenario: Summary-only refresh after revision
- **WHEN** the writer selects Summary only, generates and accepts replacement summaries
- **THEN** only that scene's detailed/brief record, updated time and text hash change; state bytes, state-history membership and existing scene flags remain unchanged
- **AND** status changes the summary from stale to ok when its hash matches the active manuscript

#### Scenario: Default and unavailable scenes
- **WHEN** no scene is explicitly chosen, or an explicitly chosen scene is missing, empty or not done
- **THEN** default selection is the first done scene without `state_updated`, with the CLI's no-waiting-scene message if none exists
- **AND** a missing/empty scene is refused with the existing message, while a not-done scene with text is allowed with the existing warning

#### Scenario: Earlier-scene warning
- **WHEN** full update-state targets a scene before scenes already marked state_updated
- **THEN** their IDs and the CLI's state-before/summary-only warning appear before a provider call, with explicit Continue anyway or Cancel and a Summary only alternative
- **AND** declining makes no call or continuity write; summary-only does not require the full-state override

### Requirement: Malformed continuity output and author edits remain recoverable
The desktop SHALL retain malformed raw output and finish/section warnings,
allow raw correction or regeneration, and prevent acceptance until all required
sections are nonempty. Saving an edit SHALL preserve existing input history
without implicitly accepting its proposed continuity.

#### Scenario: Correct raw output
- **WHEN** the fake summarizer omits a required section and the writer saves a raw correction
- **THEN** acceptance stays disabled until the existing section parser accepts detailed/brief and, except in summary-only, updated state
- **AND** the correction is retained in `inputs/state_raw_<scene>.md` and its timestamped `inputs/history` version even if it is still invalid

#### Scenario: Edit, regenerate and quit a valid preview
- **WHEN** the writer saves section edits, regenerates or quits without Accept
- **THEN** section edits use `inputs/state_edit_<scene>.md` and existing input-history names, and regeneration uses the same captured prompt inputs
- **AND** no summaries, state backup, state.md or scene-flag write occurs; explicitly saved edit-input history remains available

### Requirement: Compress validates the CLI range and replacement rules
The desktop SHALL select inclusive From/To scenes in saved scene order,
reject invalid boundaries, reversed ranges and missing summaries, and require
an explicit Replace override for overlaps before generation. Replacement
confirmation SHALL name every existing arc that will be removed.

#### Scenario: Invalid ranges do not request the provider
- **WHEN** a boundary is unknown, To precedes From, or any included scene lacks a summary
- **THEN** the existing CLI validation message identifies the error or missing IDs and no request or summary write occurs
- **AND** equal boundaries are valid when the scene has a summary; stale-but-present summaries remain eligible as in the CLI

#### Scenario: Replace whole overlapping arcs
- **WHEN** a range intersects or shares an endpoint with one or more existing valid-boundary arcs
- **THEN** generation without Replace is refused with the existing overlap/use-replace message
- **AND** confirming Replace lists whole affected arcs, including portions outside the new range; declining makes no call or write
- **AND** arcs whose endpoints are absent from the scene list are ignored for overlap as in the CLI

### Requirement: Arc previews never implicitly write summaries
Compress SHALL offer full text/word-count preview, Edit, Regenerate, Accept
and Quit. Only Accept SHALL replace all overlapping arcs and append the new
arc using existing summary serialization; per-scene summaries and unrelated
arcs SHALL remain intact.

#### Scenario: Edit and accept a replacement
- **WHEN** the writer saves an edited arc preview and subsequently presses Accept with confirmed Replace
- **THEN** the edit is retained as `inputs/arc_<from>_<to>.md` and its timestamped input history
- **AND** Accept removes whole overlapping arcs and appends one `{from, to, text, updated}` record, preserving nonoverlapping arcs and scene summaries

#### Scenario: Tags, regeneration and cancellation
- **WHEN** the provider returns untagged arc text, or the writer regenerates or quits the preview
- **THEN** untagged text remains previewable with the existing missing-summary-tags warning, regeneration uses the same range/prompt, and Quit changes no arcs
- **AND** viewing/regenerating/saving an edit alone never commits or deletes an arc; no new arc-version storage format is introduced

### Requirement: Critique reports can be generated and edited in the desktop
The desktop SHALL run the selected scene's existing critic request in the
background, surface progress/context/tag warnings/errors and Stop, and offer
a complete report preview with explicit Save. Existing and new critique
reports SHALL be editable without an external editor.

#### Scenario: Generate and save a critique
- **WHEN** Critique finishes for a scene with active text and the writer saves its preview
- **THEN** `critiques/<scene>.md` contains the existing `# Critique <scene> (<time>)` heading, blank line, extracted body and final newline
- **AND** a replaced report is copied first to `<scene>_prev_<stamp>.md`; untagged output retains the CLI warning, and a failed/stopped/unsaved result leaves the previous report intact

#### Scenario: Save review-note edits
- **WHEN** the writer edits a saved critique to remove a disputed point and saves
- **THEN** the same Markdown report path contains those edits without an added wrapper/schema, and the prior critique uses the existing prev-backup convention
- **AND** a later Revise action consumes the saved text, not unsaved report-editor contents

### Requirement: Scene and all-scene checks are deterministic and savable
The desktop SHALL run checks for one selected scene or all scenes without
provider access, display the existing report/messages and offer explicit
Save. Saved reports SHALL retain their existing paths/format and support
plain-text review-note editing.

#### Scenario: Check active paths and save the report
- **WHEN** the writer runs scene or all-scene Check against text containing banned phrases and repeated ngrams
- **THEN** only active paths contribute, empty scenes are skipped, and heading/time, snippets/node locations, counts/order, `(none)` messages and trailing newline match CLI output
- **AND** Save writes `checks/<scene>.md` or `checks/all.md`, with no new automatic backup scheme
- **AND** no provider instance, credential requirement or HTTP call is involved

#### Scenario: Edit notes and preserve scope
- **WHEN** a saved check report is edited/saved or an all-scene report exists without a scene-specific report
- **THEN** the editor saves the exact Markdown at the selected existing report path
- **AND** Revise reads only `checks/<scene>.md` and `critiques/<scene>.md`, not `checks/all.md`, matching CLI note selection

### Requirement: Revision presents one active passage at a time
The desktop SHALL revise the selected scene's captured active chain in order
using saved critique and/or scene-check notes. Each changed passage SHALL
show original/proposed text, existing word diff/counts and Accept, Skip, Edit,
Regenerate and Quit. No passage SHALL change without explicit Accept.

#### Scenario: Accept then skip
- **WHEN** two passages receive revisions and the writer accepts the first and skips the second
- **THEN** only the first node text changes, its old text is appended as `{time, text, by: "revise"}` history, and node IDs/head/branches/separators/metadata remain unchanged
- **AND** the next request uses the last 900 characters of the now-current preceding active text, and continuation leading whitespace is retained
- **AND** the view shows revised count and a stale-summary recovery action without auto-refreshing summaries

#### Scenario: No changes, warnings and prerequisites
- **WHEN** the editor returns NO CHANGES, identical trimmed text, untagged text or a length-limited response, or a scene lacks active text/scene-specific notes
- **THEN** no-change passages advance without a save, missing tags/truncation show existing warnings, and missing text/notes show the existing actionable error without a request
- **AND** the request's output cap follows the CLI editor max-tokens versus twice-original-word-count rule

#### Scenario: Edit, regenerate and quit
- **WHEN** the writer saves an edited proposal, regenerates that passage, or quits after an earlier acceptance
- **THEN** the edit is saved under `inputs/revise_<scene>_<node>.md` and timestamped input history but still needs Accept to change the node
- **AND** regeneration repeats that passage's captured request, empty edits cannot replace prose, and Quit retains earlier accepted changes without revising remaining passages

### Requirement: Status is a complete read-only overview
The desktop SHALL display the CLI's project identity/root, role models and
ceilings/sources, writer preset name/temperature or missing-preset message,
active lorebooks, scene chapters/status/words/targets/summary freshness/
critique presence/title, total/project words and arc count. Viewing status
SHALL make no provider call, lore-registry write or other project mutation.

#### Scenario: Overview matches saved CLI facts
- **WHEN** the writer opens or refreshes Status for a project with a missing/present preset, active/missing lorebooks, branches and missing/stale/current summaries
- **THEN** every displayed fact matches the CLI calculations for the same saved sources and only active-chain words count
- **AND** file bytes and directory membership remain unchanged, credentials are not exposed, and unreadable/broken sources show errors rather than invented complete totals

### Requirement: Export uses a desktop destination and existing manuscript format
The desktop SHALL offer a Save-file dialog defaulting to project
`manuscript.md`, confirm overwrite of an existing destination, and export
saved active paths using the CLI's exact Markdown. Success SHALL report
resolved path and word count; cancellation/failure SHALL never claim success.

#### Scenario: Export and reopen
- **WHEN** the writer chooses a new destination and exports scenes spanning multiple chapters, same-chapter breaks, empty scenes and inactive branches
- **THEN** the file exactly matches CLI export for the same sources, including title, chapter transitions, scene separators and final newline
- **AND** only saved active text contributes; project files/heads remain unchanged and the displayed word count/path match the written file

#### Scenario: Cancel or refuse overwrite
- **WHEN** the picker or overwrite confirmation is cancelled, the destination changes after confirmation, or the chosen path is unsafe/unwritable
- **THEN** no existing destination is overwritten, an appropriate cancellation/error is shown, and the writer can retry without losing local edits

### Requirement: Review work is serial, responsive and cooperatively stoppable
All review operations SHALL share the existing single-operation lifecycle:
reading remains usable, conflicting actions are disabled, progress/results
arrive safely, and Stop is cooperative at request/chunk/save boundaries.
Closing while busy SHALL offer Stop and wait or Keep open, not kill work.

#### Scenario: Stop or close during work
- **WHEN** a fake provider pauses, the writer presses Stop repeatedly or chooses Stop and wait on close
- **THEN** no partial report/state/arc/passage is committed, prior saved inputs/reports and accepted revisions survive, and the UI remains responsive until bounded request settlement
- **AND** close occurs only after settlement and dirty-input resolution; Keep open lets work continue, and errors/Stop restore controls with an accurate saved-work message

#### Scenario: One operation and no late cross-project result
- **WHEN** a review operation runs and another write/generation/project switch is attempted, or a late result arrives for an old operation
- **THEN** conflicting work cannot start and the late result cannot replace the current scene/project preview or editor contents

### Requirement: Stale sources and dirty editors cannot be silently overwritten
Each review write SHALL verify captured source and destination bytes and
safe targets before mutation. Changed sources SHALL require reload/retry,
not overwrite. Refresh, scene/project switching, regeneration and close
SHALL preserve dirty input or offer Save/Discard/Cancel; saving a local
preview edit SHALL NOT accept it.

#### Scenario: Sources change during preview or work
- **WHEN** an external change affects a captured tree/head, scene/order, config, bible/state, summary, relevant notes or report/export destination before its pending write
- **THEN** that write is refused with reload/retry guidance and no overwrite/backup based on stale data
- **AND** local edits remain available; a fresh operation/preview and fresh replacement confirmation are needed

#### Scenario: Dirty review editor survives refresh and navigation
- **WHEN** an edited raw/section/arc/report/revision pane refreshes or the writer navigates, regenerates or closes
- **THEN** refresh keeps text/cursor/scroll/selection, and a destructive transition offers Save/Discard/Cancel before losing edits
- **AND** failed/stale Save cancels the transition; Save persists appropriate input history or report edits, never accepts an unrelated proposal or starts the next provider call implicitly

### Requirement: Offline coverage and real Wayland acceptance remain distinct
The project checks SHALL execute headless parity/safety tests and offscreen
button-flow coverage of this journey without live credentials/network,
terminal helpers or private fixtures. Missing runtime/failing cases SHALL
fail checks, not skip. Real native Wayland acceptance SHALL be recorded
separately and remain PENDING when unavailable.

#### Scenario: Completed scene to manuscript under project checks
- **WHEN** `./scripts/check.sh` runs with installed dependencies and fake-provider fixtures
- **THEN** it runs the completed-scene → continuity → compression → critique/check → accept/skip revision → status → destination-export/reopen journey, plus rejection/dirty/stale/Stop/error coverage and existing tests
- **AND** syntax, CLI help and discovered tests pass with no weakened network guard or skip; a failing journey fails the script

#### Scenario: Full-workspace acceptance is not inferred
- **WHEN** milestone 3's offline tests pass without a usable owner Wayland desktop
- **THEN** the evidence records compositor acceptance as PENDING, not passed from offscreen results
- **AND** the full roadmap parity matrix is audited across Create through export and all draft actions before any workspace-completion claim; this proposal authorizes neither implementation completion nor shipping
