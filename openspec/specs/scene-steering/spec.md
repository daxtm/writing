# scene-steering Specification

## Purpose

Let writers persist multiline direction for each current scene while protecting unsaved edits and preserving existing CLI tree semantics.

## Requirements

### Requirement: Save and Clear persist per-scene steering
For a valid current scene the editor SHALL load its saved tree-level steering, defaulting to empty. Save SHALL persist the current multiline text exactly as `steer` in that scene's existing tree format; Clear SHALL immediately persist an empty value. Successful saves SHALL clear the dirty indication without changing nodes, head, counter, candidate metadata, or other fields.

#### Scenario: Save, reopen, and clear
- **WHEN** the owner types multiline direction and presses Save steering
- **THEN** status confirms saving and reopening the project restores the same text for that scene
- **AND** another scene's steering and every existing tree field other than tree-level `steer` remain unchanged
- **WHEN** the owner presses Clear
- **THEN** the editor and persisted `steer` become empty, remain empty on reopen, and no candidate's recorded steering is rewritten

#### Scenario: Current scene has no tree yet
- **WHEN** a valid current scene without a tree is selected and steering is saved
- **THEN** only that scene's ordinary empty tree with steering is created, with no nodes, null head, and counter zero
- **AND** no other project source is created or changed

#### Scenario: Retained or damaged tree
- **WHEN** a retained tree without a current scene card, an invalid scene, or a malformed/unreadable/unsafe tree is selected
- **THEN** reading remains available where possible but steering writes are disabled with a reason
- **AND** no malformed source is replaced with an empty tree

### Requirement: Dirty navigation and close require a choice
Leaving a scene with unsaved steering, including window close, SHALL offer Save, Discard, or Cancel. Save SHALL proceed only after successful persistence; Discard SHALL leave disk unchanged; Cancel SHALL leave scene, selection, editor, and window intact. Node/tab navigation within the same scene SHALL retain the editor without prompting.

#### Scenario: Scene switch choices
- **WHEN** a dirty scene is left and the owner chooses Save
- **THEN** its steering is saved before the new scene's steering is loaded
- **WHEN** Discard is chosen instead
- **THEN** navigation proceeds with no write to the old scene
- **WHEN** Cancel is chosen instead
- **THEN** selection and dirty text remain on the original scene

#### Scenario: Close and failed save
- **WHEN** the owner closes a dirty window
- **THEN** the same three choices are offered and Cancel keeps the window open
- **WHEN** Save fails during close or scene switching
- **THEN** the window stays on the original scene with its dirty text and an actionable status error

### Requirement: External changes and write failures cannot silently lose edits
Save/Clear SHALL reject stale tree contents, changed scene identity, unsafe paths, and invalid sources before writing. A rejected write SHALL preserve dirty text and show recovery guidance. A confirmed reload/discard SHALL be required to replace dirty text with externally saved steering. Concurrent CLI/GUI writers are unsupported; this is stale-input detection, not a transaction.

#### Scenario: External tree edit before Save or Clear
- **WHEN** the tree changes externally after steering was loaded or a previously absent tree appears, then Save or Clear is requested
- **THEN** the operation refuses to overwrite it, preserves editor text, and reports that saved data changed
- **AND** the owner can explicitly choose Reload saved steering or Keep editing; refresh alone never acknowledges the conflict on behalf of the owner

#### Scenario: Unsafe destination or save error
- **WHEN** the tree directory/file becomes symlinked, the scene disappears, or persistence fails
- **THEN** Save/Clear fails with a sanitized error, preserves unsaved editor text, and does not report success
- **AND** no write follows a symlink or changes another scene, accepted head, or saved node

### Requirement: Steering controls do not draft
This shell SHALL perform no model/provider calls or manuscript acceptance. Save steering SHALL be the primary action, with Generate visibly unavailable and explained. Its saved per-scene direction SHALL remain compatible with existing CLI draft behavior.

#### Scenario: Save while offline
- **WHEN** the owner reads branches and saves/clears steering with credentials absent and network connections refused
- **THEN** these actions succeed without API access, new candidates, or accepted-head changes
- **AND** the existing CLI can load the same tree and retrieve the saved tree-level direction
