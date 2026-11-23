# Proposal

## Why

Milestone 1 needs a usable native Wayland reading and steering foundation before adding drafting. Existing CLI steering requires terminal interaction, and the pending Tk reader cannot provide the chosen Qt workspace or edit steering; reuse its safe reader model instead of building another reader.

## What Changes

- Add blocking `gui DIR` with one Qt Widgets window, explicit native Wayland startup, actionable startup failures, and lazy GUI imports.
- Bring across only the pending UI-independent snapshots, synthetic builders, and model tests, replacing the Tk presentation entirely.
- Show current/retained scenes, every saved branch and its metadata, manuscript, and notes in a resizable, keyboard-usable layout with adjustable prose size and system light/dark colors.
- Add multiline per-scene steering: Save, persistent Clear, and Save/Discard/Cancel on dirty scene changes or close. Refresh saved content about every two seconds without losing reading position or dirty text.
- Provision tested PySide6 in the existing launcher/check path; distinguish offline widget tests from desktop acceptance.

## Capabilities

### New Capabilities

- `desktop-reading`: native project reading, safe snapshots, navigation, presentation, and refresh.
- `scene-steering`: persistent steering and dirty-editor protection.

### Modified Capabilities

- `offline-regression`: provision Qt and run widget coverage offscreen without weakening headless tests or network guards.

## Impact

Implementation touches the launcher dependencies, CLI dispatch, reader/Qt modules, tests, and existing `scripts/check.sh`. PySide6 increases clean-checkout downloads/disk use even for CLI users; no second runner.

## Out of Scope

Generation, previews of new output, acceptance, Stop, and the background worker belong to the subsequent `gui-steered-drafting` change. No Tk UI, new file format, provider call, or other project editing.

## Demo After Implementation

`QT_QPA_PLATFORM=wayland uv run --script longform.py gui /path/to/project`

Expect one window with scenes/branches, readable saved prose/notes, steering Save/Clear, and status. Save direction, close/reopen, and see it retained.
