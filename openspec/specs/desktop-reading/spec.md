# desktop-reading Specification

## Purpose

Let writers read every saved branch and supporting note in a native Wayland workspace without changing their manuscript or exposing unrelated project data.

## Requirements

### Requirement: Native desktop entry point
`gui DIR` SHALL open one native desktop window for an existing valid project and block until it closes. It SHALL require native Wayland, defaulting to Wayland when no platform is selected, and never silently fall back to XWayland.

#### Scenario: Launch and close
- **WHEN** the owner runs `QT_QPA_PLATFORM=wayland uv run --script longform.py gui DIR` in a working Wayland session for a valid synthetic project
- **THEN** one project window opens and the command stays running until the window closes
- **AND** startup reports the actual platform as `wayland` and closing without edits exits successfully

#### Scenario: Explicit fallback configuration
- **WHEN** `gui DIR` is launched with an explicit platform other than exactly `wayland`, including a fallback list
- **THEN** it exits nonzero with a diagnostic directing the owner to `QT_QPA_PLATFORM=wayland`
- **AND** no XWayland or offscreen project window is opened by this command

### Requirement: Startup failures are actionable
Missing GUI dependencies, missing Wayland session support, or platform initialization failure SHALL produce a nonzero exit and actionable stderr diagnostics, not a silent fallback or a credential-bearing traceback.

#### Scenario: Missing Qt
- **WHEN** the GUI dependency cannot be imported and `gui DIR` is invoked
- **THEN** stderr identifies the missing GUI runtime and recommends `uv run --script longform.py gui DIR` to provision the declared dependency
- **AND** no project files change

#### Scenario: Wayland cannot initialize
- **WHEN** native platform startup fails, including unavailable session/socket or platform libraries
- **THEN** stderr includes guidance to use a Wayland desktop, check its session/socket and Qt platform/system libraries, and retry the explicit Wayland command
- **AND** the command fails without starting an alternate platform

### Requirement: CLI and model use need no GUI startup
Non-GUI commands and reader snapshots SHALL remain usable without Qt imports or a display. CLI help SHALL include `gui` without initializing a GUI.

#### Scenario: Headless help and snapshot import
- **WHEN** CLI help and snapshot imports run with no display variables and GUI imports made unavailable
- **THEN** help succeeds and lists `gui`, and the model loads a synthetic project
- **AND** neither execution imports a GUI toolkit or starts a provider request

### Requirement: Safe snapshot reading
The reader SHALL load only its allowlisted public project fields and saved sources beneath one canonical root. It SHALL refuse symlinks below that root, unsafe IDs, and path escapes, with sanitized relative-source warnings. Loading or navigating SHALL not write project files or expose credentials, presets, logs, or arbitrary configuration.

#### Scenario: Unrelated and linked secrets
- **WHEN** a synthetic project includes credential fields, `.env`, writer presets, API logs, unallowlisted files, unsafe tree IDs, and symlinked sources
- **THEN** none of those contents appears in snapshots, UI panes, or warnings
- **AND** safe unrelated prose remains readable and rejected sources are identified without raw values or absolute paths

#### Scenario: Required and optional failures
- **WHEN** required `project.json` is missing or invalid at startup
- **THEN** the command reports a sanitized error, exits nonzero, and does not create a project
- **WHEN** an optional source is absent, malformed, unreadable, or has broken links
- **THEN** unaffected sources remain readable, missing optional files show an empty state, and damaged sources show warnings rather than crashing

### Requirement: Current and retained trees remain readable
The sidebar SHALL preserve current scene-card order and chapter grouping, distinguish retained trees without cards, and expose every saved node, not just the active path. Reading selection SHALL never move the accepted head. Current-scene totals SHALL exclude retained and inactive branches and label incomplete totals.

#### Scenario: Explore an inactive branch and retained tree
- **WHEN** the owner selects a sibling node or a retained tree without a scene card
- **THEN** its saved text is readable and active-head/path markers remain distinguishable
- **AND** the current-scene total and persisted head do not change

#### Scenario: Saved metadata and broken chains
- **WHEN** a saved node is selected
- **THEN** its available ID, parent/children, word count, source/model, creation time, steering used, ended/trimmed flags, and revision history are readable as plain text
- **AND** absent metadata has an empty/absent indication rather than fabricated values
- **WHEN** a cycle or dangling link prevents assembling the active manuscript
- **THEN** individual saved nodes remain readable, active text is marked unavailable, and totals are marked partial

### Requirement: Supporting notes are literal and read-only
The workspace SHALL display bible, continuity state, scene detailed/brief summaries, arc summaries, and all direct check/critique Markdown files including sorted backups. These panes and manuscript/saved-node panes SHALL be read-only and display markup literally.

#### Scenario: Read all note sources
- **WHEN** the owner selects Notes for a synthetic project containing every supported source and a critique backup
- **THEN** every supported text is accessible, reports/backups are sorted by filename, and Markdown is not interpreted as active content
- **AND** typing or paste in a reading pane cannot modify text or files

### Requirement: Usable reading and steering layout
The window SHALL provide a resizable scene/branch sidebar, manuscript and saved-candidate reading area, notes, multiline steering with Save/Clear, and persistent status/error area. It SHALL use consistent typography/spacing, system light/dark colors with readable contrast, visible keyboard focus, and adjustable prose size.

#### Scenario: Resize and keyboard navigation
- **WHEN** the owner resizes the window and sidebar, tabs through controls, and increases/decreases prose size
- **THEN** reading panes expand, controls remain accessible, focus is visible, and only presentation changes
- **AND** Save steering is the clear primary action, while Generate is disabled with an explanation that drafting is not available yet

#### Scenario: Palette and reading comfort
- **WHEN** the window is exercised with light and dark system palettes
- **THEN** prose, selection, editor, disabled controls, and error text use readable foreground/background combinations without fixed light-only colors

### Requirement: Refresh preserves reading and editing state
Automatic refresh about every two seconds and an explicit Refresh action SHALL incorporate saved-source changes using cached unchanged sources. Refresh SHALL preserve selected scene/node, tab, reading scroll, focus, and dirty steering. It SHALL not write files, silently replace dirty text, or discard a dirty scene that disappears.

#### Scenario: Content changes while steering is dirty
- **WHEN** the owner scrolls an inactive node, selects a tab, edits steering without saving, and a saved note/tree changes before refresh
- **THEN** updated read-only content appears while selection, tab, focus, dirty editor text/cursor, and scroll remain stable where content permits
- **AND** a removed node gets an explicit unavailable indication, not silent selection of a different node

#### Scenario: Unchanged and forced refresh
- **WHEN** automatic refresh runs with unchanged source metadata
- **THEN** cached optional sources are not reread
- **WHEN** the owner explicitly requests Refresh
- **THEN** sources are reread even if their timestamps and sizes were preserved, without resetting dirty steering or reading position

#### Scenario: Selected dirty scene or required configuration disappears
- **WHEN** refresh finds the dirty editor's scene removed or required configuration invalid
- **THEN** the window keeps the unsaved text and last readable view visibly marked unavailable/stale, disables unsafe saves, and explains recovery
- **AND** after valid sources are restored a later refresh recovers without restarting the application

### Requirement: Open the workspace with a bare invocation
Running the program without a command SHALL open the native desktop workspace
for the current working directory, equivalent to `gui [DIR]` with `DIR`
defaulting to the current directory. It SHALL NOT report a missing-command
argument error. `--help`, every explicit command, and the native-Wayland-only
policy SHALL keep their existing behavior.

#### Scenario: Launch without arguments from a project
- **WHEN** the owner runs the source launcher with no command from a project directory in a working Wayland session
- **THEN** one native workspace opens for that directory and blocks until it closes
- **AND** no argument error and no fallback platform window are produced

#### Scenario: Launch without arguments from a non-project directory
- **WHEN** the source launcher starts with no command from a directory that is not a project
- **THEN** the workspace opens with its Create/Open controls and explicit warnings
- **AND** no project file is written until the owner confirms Create or Open

#### Scenario: Help remains available without a display
- **WHEN** the launcher runs `--help`
- **THEN** it lists the existing commands, including `gui [DIR]`, and opens no window
