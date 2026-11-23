## Purpose

Let a writer read all saved manuscript branches and supporting notes in a native desktop window while continuing to draft through the CLI.

## ADDED Requirements

### Requirement: Launch and close a native desktop reader
The CLI SHALL provide `gui DIR`, opening one native desktop window and blocking
until it closes. The command SHALL bypass shared project construction, require
no API credentials, and perform no provider calls, browser launches, or server
startup. Other CLI commands and help SHALL work without Tk or a display.

#### Scenario: Dispatch without constructing the shared project
- **WHEN** `gui DIR` is invoked with a fake desktop launcher and shared project construction configured to fail
- **THEN** the launcher receives DIR exactly once and shared project construction is not called
- **AND** CLI help lists `gui` without loading Tk

#### Scenario: Close the actual window
- **WHEN** a valid project is opened on a Tk-capable display and the writer closes the window or presses Ctrl+Q
- **THEN** the native window closes, its refresh timer stops, and the command returns without a traceback

#### Scenario: Missing runtime support or invalid project
- **WHEN** Tk cannot be imported, no display can be opened, or DIR lacks a readable valid project configuration
- **THEN** startup exits nonzero with a concise diagnostic and no raw configuration, credentials, or traceback
- **AND** missing Tk/display diagnostics direct the writer to the documented uv runtime and a desktop display

### Requirement: Scene selection shows saved writing progress
The left scene list SHALL display current scene ID, title, status, and active
word count in card order. Retained `trees/*.json` without current scene cards
SHALL appear in a separate labeled group and remain selectable. Project totals
SHALL count current scenes' active text only and show the configured target.
Selecting a scene SHALL update its Manuscript and Branches views.

#### Scenario: Current, empty, and retained scenes
- **WHEN** a project contains current scenes, inactive swipes, an empty scene, and a tree with no current card
- **THEN** every current scene and the retained tree are listed with their counts
- **AND** the retained tree is labeled separately and excluded from current-scene totals
- **AND** selecting any scene displays that scene rather than the previously selected scene

#### Scenario: No scene cards
- **WHEN** the optional scenes file is absent or contains an empty list
- **THEN** the list shows a clear empty state for current scenes, current totals are zero, and any retained trees remain selectable

### Requirement: Read the full active manuscript
The Manuscript tab SHALL show the selected scene's full active chain as
read-only word-wrapped prose with scrollbars, current head ID, and word count.
Text assembly and counts SHALL match existing tree text and word semantics.
An absent head SHALL produce a labeled empty manuscript without hiding saved
candidate nodes in Branches.

#### Scenario: Continuations and paragraph separators
- **WHEN** a scene with leading whitespace, default paragraph separators, and empty-separator continuations is selected
- **THEN** its full manuscript exactly matches the existing active-chain text and its word count
- **AND** long text remains accessible by scrolling rather than truncation

#### Scenario: Unaccepted candidates
- **WHEN** a selected tree contains saved nodes but has no head
- **THEN** Manuscript shows an empty state with zero words and Branches still lists every saved node

### Requirement: Read every saved branch and its history
The Branches tab SHALL index every persisted node, including inactive siblings,
descendants, and nodes outside the active chain. The index SHALL show ID, words,
source, creation time, head and active-path markers. Selecting a node SHALL show
full untruncated text, parent/child navigation, model, steer used, ended/trimmed
flags, and saved edit history with time, author, and full prior text.

#### Scenario: Navigate inactive siblings and descendants
- **WHEN** the writer selects an inactive node, then navigates to its child or parent
- **THEN** each selected node's complete text and metadata are readable, including all saved history entries
- **AND** navigation changes only the reader's selection, not the saved head or active manuscript

#### Scenario: Missing optional metadata
- **WHEN** a node lacks optional metadata while another has explicitly false ended/trimmed flags
- **THEN** missing metadata is labeled unavailable and false flags are displayed as false
- **AND** both nodes' full text remains readable

### Requirement: Read supporting notes as plain text
The Notes tab SHALL show bible, continuity state, detailed/brief scene summaries,
arc summaries with scene ranges, and all direct Markdown reports in checks and
critiques, including saved previous reports. Each source SHALL have a clear
heading or filename and missing sources SHALL have empty states. Content SHALL
preserve paragraphs without executing or rendering markup.

#### Scenario: All supported notes and missing files
- **WHEN** a fixture contains distinctive text in each supported source and an older critique, while one optional source is absent
- **THEN** every saved note is readable under a recognizable heading, the absent source is labeled empty, and markup appears literally
- **AND** scene summaries are identified by scene and arc summaries by their saved ranges

### Requirement: Refresh without losing reading position
The reader SHALL provide Refresh now, F5, and an Auto-refresh toggle enabled by
default at approximately two-second intervals. It SHALL show last refresh time
and project totals, detect saved changes without an export, and avoid automatic
reloads of unchanged content. Manual refresh SHALL force a fresh disk read.
Refresh SHALL preserve surviving scene/node selections,
selected tab, list expansion, and scroll positions.

#### Scenario: Another draft is saved
- **WHEN** a new inactive node is saved while the writer is scrolled within an existing scene/node and a refresh runs
- **THEN** the new node appears and counts/head reflect disk content
- **AND** the selected scene, node, tab, expansion, and reading position remain unchanged where still present

#### Scenario: Automatic refresh is disabled
- **WHEN** the writer disables Auto-refresh and another file is saved
- **THEN** elapsed timer intervals do not reload content, but Refresh now or F5 loads the change
- **AND** re-enabling Auto-refresh resumes polling without duplicate timers

#### Scenario: Unchanged sources and removed selection
- **WHEN** automatic refresh finds unchanged sources, or the selected node/scene has been removed
- **THEN** unchanged sources are not reread or their panes rebuilt
- **AND** a removed node falls back to the scene's current head then first saved node, and a removed scene falls back to the first current scene then first retained tree, or an empty state
- **AND** the displayed last refresh time records the completed check

#### Scenario: Force a fresh read
- **WHEN** an external editor changes content while preserving its file size and modification time and the writer presses F5
- **THEN** the saved change appears even if automatic change detection found no metadata difference

### Requirement: Load safe snapshots without a display
The reader SHALL expose UI-independent, data-only project snapshots usable
without importing Tk, constructing the CLI project, exiting the process, or
making provider calls. Missing optional files SHALL yield empty data; malformed
JSON, invalid shapes, unreadable sources, or invalid tree links SHALL yield
sanitized source warnings without hanging or hiding unrelated valid writing.

#### Scenario: Malformed optional data and recovery
- **WHEN** snapshot loading encounters malformed scenes, summaries, or one tree file
- **THEN** affected content is labeled unavailable, other valid sources remain readable, and no loader exits the process or reveals raw JSON
- **AND** totals are labeled partial when an unreadable current tree prevents a complete active-word count
- **AND** restoring valid content makes it available on the next refresh

#### Scenario: Cyclic or broken tree links
- **WHEN** a saved tree has a parent cycle or missing head/parent reference
- **THEN** loading terminates with a warning, does not attempt an invalid active-chain traversal, and keeps well-formed saved node text readable

#### Scenario: Required configuration fails during refresh
- **WHEN** project configuration becomes unreadable or invalid after a successful load
- **THEN** the last valid snapshot stays visible with a stale-data warning and refresh remains available
- **AND** a subsequent successful refresh clears the warning

### Requirement: Show only allowlisted writing and public project identity
Snapshots and widgets SHALL expose only project title/target, scene display
fields, saved node reading fields/history, and supported notes. They SHALL NOT
expose other configuration fields, credentials, environment values, presets,
call logs, or arbitrary files. Unsafe scene IDs and symlinked sources below the
chosen canonical root SHALL be refused; diagnostics SHALL NOT echo raw inputs
or file contents.

#### Scenario: Synthetic secrets do not leak
- **WHEN** configuration, unknown node/summary fields, environment, preset, and logs contain synthetic secrets not present in supported writing
- **THEN** no snapshot, widget, stdout, stderr, or error message contains those secrets
- **AND** configuration contributes only validated title and target values

#### Scenario: Linked files and unsafe identifiers
- **WHEN** a scene ID attempts path traversal or an allowlisted file/directory below the root is a symlink
- **THEN** the source is skipped with a sanitized warning and linked/outside contents are not read or displayed

### Requirement: The desktop interface is readable and strictly read-only
The window SHALL show project title and a read-only label, sensible minimum
dimensions, readable typography, a resizable scene list, and Manuscript,
Branches, and Notes tabs. Text SHALL support selection, copying, word wrapping,
and scrolling, but no typing, paste, editing, generation, or branch acceptance.
Opening, navigating, refreshing, and closing SHALL NOT write project files.

#### Scenario: Read without modifying the project
- **WHEN** the writer opens a synthetic project, switches scenes/nodes/tabs, attempts typing and pasting, refreshes, and closes
- **THEN** text remains unchanged, no editing/generation controls are present, and every project file hash and directory entry matches its pre-open value
- **AND** all operations run without browser/server startup or provider access

### Requirement: Checks cover desktop behavior offline and headless
`./scripts/check.sh` SHALL discover model, fake-launcher CLI, and desktop smoke
tests through the existing pytest suite. Model and CLI tests SHALL run without
Tk/display. Real-widget smoke tests SHALL create a withdrawn window when Tk and
a usable display are available and skip cleanly only when unavailable, without
weakening existing network guards or adding dependencies.

#### Scenario: Headless checks
- **WHEN** the check script runs without a usable display or Tk installation
- **THEN** model and CLI coverage passes, widget tests report a clear skip reason, and the script exits zero with the existing suite passing

#### Scenario: Display-capable checks
- **WHEN** the check script runs with working Tk and a display
- **THEN** withdrawn-widget tests verify scene/text population, inactive-node reading, refresh selection/scroll preservation, and clean timer/window teardown
- **AND** a widget assertion failure fails checks rather than being treated as an availability skip
