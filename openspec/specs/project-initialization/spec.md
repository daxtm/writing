# project-initialization Specification

## Purpose

Give CLI and desktop writers complete, portable new-project setup from reviewed nonsecret defaults without replacing existing work or requiring private source files.

## Requirements

### Requirement: Initialization creates complete local setup
CLI init and GUI Create SHALL use the same initialization behavior to create
the five existing default files, seven existing directories and a usable
`writer_preset.json`. Initialization SHALL NOT fetch limits, generate story
content or contact the provider.

#### Scenario: Initialize a fresh directory
- **WHEN** CLI init or GUI Create confirms a missing or empty project directory without selecting a preset
- **THEN** `project.json`, `bible.md`, `state.md`, `scenes.json`, `summaries.json` and `writer_preset.json` exist as regular files
- **AND** `trees/`, `outlines/`, `critiques/`, `checks/`, `state_history/`, `lorebooks/` and `bible_history/` exist as directories
- **AND** the bible/state templates and empty scene/summary contents retain their existing formats, the preset passes existing master-export validation and can be loaded for writing without a preset picker
- **AND** no provider request, generated outline, accepted scene or limits file is created

### Requirement: New projects receive reviewed sanitized owner defaults
New `project.json` files SHALL retain supported nonsecret defaults from the
owner-selected source, except that `api_key` SHALL be empty, `api_key_env`
SHALL be `FEATHERLESS_API_KEY`, and the writer preset path SHALL be
`writer_preset.json`. Bundled defaults SHALL be reviewed recursively to exclude
credentials and private project data.

#### Scenario: Initialize from the reviewed runtime defaults
- **WHEN** a new configuration is created from the application-owned defaults
- **THEN** supported role/model, sampler, prompt, budget, review and project settings match the reviewed source-derived values except the three forced fields
- **AND** an explicitly supplied project title takes precedence for a new configuration; otherwise the title is `Untitled`
- **AND** no credential from the source or current environment is copied into any initialized file

#### Scenario: Review distributed assets without private fixtures
- **WHEN** the maintainer inspects the tracked defaults, provenance and distributed notices
- **THEN** they identify the two source filenames and the required sanitizing overrides without including the original files, source credentials, private story content or home-directory runtime dependencies
- **AND** synthetic nested credential/path sentinels in unsupported metadata used to test defaults validation are rejected or excluded without reaching accepted output or diagnostics

### Requirement: Initialization only fills missing paths
Repeated initialization SHALL preserve existing file bytes and existing
configuration, including external preset paths, and create only missing
initialization paths. Opening an existing project SHALL NOT change its saved
or effective settings merely because new-project defaults changed.

#### Scenario: Reinitialize edited or partial projects
- **WHEN** init is repeated against a project with edited configuration, bible, state, scenes, summaries, preset and drafted/history files
- **THEN** all existing bytes remain unchanged and only missing initial paths are added
- **AND** a repeated run with all initial paths present reports that nothing was created
- **AND** removing just `writer_preset.json` and repeating init restores only that missing default preset without rewriting an existing configured external preset path or the external file

#### Scenario: Keep legacy omitted-field behavior
- **WHEN** an existing project omits supported settings that previously used application fallback values
- **THEN** Open, status and settings loading retain those previous effective fallback values and leave its configuration bytes unchanged

### Requirement: An explicit preset takes precedence only for a missing destination
CLI `init DIR --preset FILE` SHALL use the existing master-export validation
and copy valid selected preset bytes unchanged instead of the bundled preset
when `writer_preset.json` is absent. An existing regular destination SHALL
remain unchanged with a not-overwritten warning.

#### Scenario: Initialize with an explicit valid override
- **WHEN** init supplies a valid master export and the destination preset is missing
- **THEN** `writer_preset.json` matches the selected file byte for byte rather than the bundled preset, and the source is not modified

#### Scenario: Keep an existing preset during override
- **WHEN** init supplies `--preset FILE` but a regular `writer_preset.json` already exists
- **THEN** that destination remains byte-identical, a not-overwritten warning is reported, and other missing initialization paths can still be filled

#### Scenario: Invalid explicit source is not silently replaced
- **WHEN** the destination is absent and the explicitly selected preset is unreadable, invalid JSON or lacks a required master-export key
- **THEN** initialization fails with an actionable diagnostic, creates no destination preset and does not silently substitute the bundled preset
- **AND** any other paths already created are reported and retained for a non-destructive retry

### Requirement: Initialization reports actual writes and failures
Initialization SHALL report files/directories actually created, preserved
destinations and failures truthfully. Unsafe path collisions SHALL be refused.
Failed or stopped initialization SHALL retain earlier complete writes and
report partial completion rather than claim success or roll back existing work.

#### Scenario: Collision or permission failure after earlier writes
- **WHEN** an initial file/directory is occupied by the wrong path type or a later write fails after earlier paths were created
- **THEN** init exits nonzero or the GUI displays failure naming the affected path and paths already created
- **AND** earlier complete writes and existing work remain intact, the GUI does not claim successful project creation, and retry after correction fills only still-missing paths

#### Scenario: Unsafe root or target
- **WHEN** the selected root or an initialization destination or temporary write path is symlinked or otherwise unsafe under the existing safe-path policy
- **THEN** initialization refuses the unsafe write without changing the linked target, and reports any earlier work accurately

#### Scenario: Stop before completion
- **WHEN** GUI initialization is stopped at a controlled boundary after a complete file was saved
- **THEN** no further paths are written after cancellation is observed, the saved file remains intact and partial completion is reported
- **AND** no incomplete preset/configuration is reported as created
