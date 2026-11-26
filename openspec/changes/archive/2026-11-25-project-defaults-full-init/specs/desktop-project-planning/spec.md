## MODIFIED Requirements

### Requirement: Create and Open work without a prepared project
The GUI SHALL offer desktop Create/Open directory selection even when launched
with a missing directory, missing configuration or no scenes. Explicit Create
SHALL perform complete shared initialization with sanitized bundled defaults,
including the writer preset, using create-missing-only semantics on both
immediate and deferred paths. Open SHALL read without initializing or requesting
the provider.

#### Scenario: Create from an empty location
- **WHEN** the writer launches `gui DIR` for a missing directory and confirms a location through Create
- **THEN** the five default project files, seven initialization directories and `writer_preset.json` are created with the same contents as CLI init using the bundled sanitized defaults
- **AND** setup controls remain usable with an empty scene list, without a terminal question, preset picker or provider call
- **AND** completion reports the preset as created and no longer identifies it as a missing drafting prerequisite

#### Scenario: Repeated initialization and cancelled selection
- **WHEN** Create targets an existing partially initialized project or the directory dialog is cancelled
- **THEN** existing files remain unchanged and only missing initialization paths, including the default preset, are created on confirmed Create
- **AND** cancelling creates nothing and leaves the current project selected

#### Scenario: Open or fail safely
- **WHEN** the writer opens an existing valid project, or selects a directory with missing, malformed or unsafe configuration
- **THEN** a valid project displays its existing content without changes or calls
- **AND** an invalid selection reports an actionable error without resetting files or replacing the currently usable project
- **AND** Open does not repair a missing preset or other initialization path

#### Scenario: Deferred Create after saving dirty settings
- **WHEN** Create for another directory is deferred until an explicit Save of the current project's dirty settings completes
- **THEN** the current settings save finishes first and the selected new directory receives the same six files, seven directories and sanitized defaults as immediate Create
- **AND** the saved old-project title or other settings do not leak into the new project, and no preset picker or provider request runs

#### Scenario: Dirty Save fails or Create is cancelled
- **WHEN** a prerequisite dirty-form Save fails, is stale or is cancelled, or the writer cancels Create
- **THEN** no deferred initialization runs, the current project remains selected and local unsaved edits remain available

#### Scenario: Partial initialization is not successful creation
- **WHEN** Create encounters a path collision, permission failure or cooperative Stop after some paths were saved
- **THEN** the GUI reports the failed/stopped path and completed writes rather than successful full initialization
- **AND** controls recover after settlement, the previously usable project remains selected and retry creates only missing paths
