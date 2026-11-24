## Purpose

Preserve comfortable saved-branch reading and unsaved editing state when the desktop workspace moves from tabs to focused writing stages.

## MODIFIED Requirements

### Requirement: Usable reading and steering layout
The window SHALL provide a resizable scene/branch sidebar, manuscript and
saved-candidate reading area, notes, Write-local multiline steering with
Save/Clear, and persistent status/error/Stop access. It SHALL use consistent
typography/spacing, system light/dark colors with readable contrast, visible
keyboard focus and adjustable prose size across its stage/tool navigation.

#### Scenario: Resize and keyboard navigation
- **WHEN** the owner resizes the window and sidebar, tabs through controls, and increases/decreases prose size
- **THEN** reading panes expand, controls remain accessible, focus is visible, and only presentation changes
- **AND** Write exposes steering Save/Clear and draft Generate with its actual prerequisite explanation, while other stages expose their own primary next actions rather than draft controls

#### Scenario: Palette and reading comfort
- **WHEN** the window is exercised with light and dark system palettes
- **THEN** prose, selection, editor, disabled controls, and error text use readable foreground/background combinations without fixed light-only colors

### Requirement: Refresh preserves reading and editing state
Automatic refresh about every two seconds and an explicit Refresh action SHALL
incorporate saved-source changes using cached unchanged sources. Refresh SHALL
preserve selected scene/node, stage/tool, reading scroll, focus and dirty
steering. It SHALL not write files, silently replace dirty text, or discard a
dirty scene that disappears.

#### Scenario: Content changes while steering is dirty
- **WHEN** the owner scrolls an inactive node, selects a stage/tool, edits steering without saving, and a saved note/tree changes before refresh
- **THEN** updated read-only content appears while selection, stage/tool, focus, dirty editor text/cursor, and scroll remain stable where content permits
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
