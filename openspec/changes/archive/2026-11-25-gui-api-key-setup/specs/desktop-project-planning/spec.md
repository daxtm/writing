## Purpose

Let writers configure usable project credentials through explicit desktop choices without revealing or unintentionally persisting their values.

## MODIFIED Requirements

### Requirement: Settings edit supported nonsecret fields only
The GUI SHALL provide validated Save/Cancel forms for supported nonsecret
project, role/model, sampler, writer, budget and review-configuration settings.
It SHALL preserve unknown/unedited fields and refresh prerequisites without a
provider call. Credentials SHALL use a separate masked control with explicit
session/storage actions, not a raw configuration editor.

#### Scenario: Supported configuration controls
- **WHEN** the writer opens Settings
- **THEN** controls cover title/target, provider base/environment name, context fallback/safety/prompt/section budgets, token-estimation ratio, concurrency/timeout, existing role models and supported chat samplers/thinking, writer preset/swipes/passage/user/lore, summary sizing, banned phrases and ngrams
- **AND** preset overrides expose existing consumed temperature/probability/top-k/penalty/output/context/DRY fields rather than new inert options

#### Scenario: Save and reopen nonsecret settings
- **WHEN** the writer changes supported models, budgets, concurrency and writer preset overrides and presses Save
- **THEN** `project.json` contains those values in the existing schema, unknown fields remain intact and reopening shows the saved settings
- **AND** no limits fetch, generation or implicit next command runs
- **AND** the credential field is preserved unless a separate credential storage action was explicitly confirmed

#### Scenario: Refuse invalid configuration
- **WHEN** a form contains a blank model, invalid environment name, nonfinite number, boolean integer, nonpositive concurrency, invalid probability, malformed list or unsupported enum
- **THEN** Save identifies the invalid fields and leaves saved configuration unchanged
- **AND** the writer's unsaved entries remain available for correction

#### Scenario: Cancel settings
- **WHEN** the writer cancels a dirty settings form
- **THEN** configuration remains unchanged and subsequent operations use saved values

### Requirement: Credential presentation never reveals a key
The GUI SHALL show effective credential source and missing/available status,
plus the configured environment name, never a stored key value. New input
SHALL be masked and never prefilled from saved/environment credentials.
Use for this session SHALL be the default nonpersistent action; nonsecret
settings saves SHALL preserve existing inline keys opaquely.

#### Scenario: Environment and legacy inline credentials
- **WHEN** a project uses an environment key or an existing inline key and the writer views or saves Settings
- **THEN** the GUI shows the environment name/status, effective availability and winning source without the key value
- **AND** no new key is stored and an existing inline field is neither displayed, changed nor migrated

#### Scenario: Missing credentials and an echoed secret
- **WHEN** credentials are absent or a fake provider failure body includes a sentinel credential
- **THEN** provider controls explain missing credentials or show a sanitized failure, without exposing the sentinel anywhere in GUI text/events
- **AND** local bible/settings/card editing remains available when its own file prerequisites are valid

#### Scenario: Entry alone has no effect
- **WHEN** the writer types a new value in the masked credential field without choosing a credential action
- **THEN** effective credentials and project bytes remain unchanged and no provider request occurs
- **AND** an ordinary Save settings cannot persist the typed value

## ADDED Requirements

### Requirement: Session credentials are isolated and used consistently
An explicitly activated session credential SHALL override project then
environment credentials for every provider action in its project/window.
It SHALL NOT mutate process environment or saved configuration. Switching
projects or closing SHALL clear it; local actions SHALL remain usable without it.

#### Scenario: One session enables all provider families
- **WHEN** project and environment keys exist and a distinct session sentinel is activated with Use for this session
- **THEN** Test connection, Fetch limits, outline, scenes, draft, continuity, compression, critique and revision use only that session credential for authentication
- **AND** project bytes and process environment are unchanged and status identifies session as the source

#### Scenario: Clear session or switch projects
- **WHEN** the writer chooses Clear session key, switches to another project or closes/reopens the window
- **THEN** the prior session credential is unavailable, with remaining source resolved as project then environment then missing
- **AND** a second window has never inherited that session credential

#### Scenario: CLI compatibility
- **WHEN** the CLI constructs its provider without a GUI session override
- **THEN** nonempty project credentials still precede the configured environment key and existing command output/arguments remain unchanged

### Requirement: Project credential persistence requires explicit informed action
Save to this project, Replace saved key and Clear saved key SHALL modify only
the existing `api_key` field after explicit confirmation. Before storage the
GUI SHALL warn that `project.json` is plaintext and sharing/backups include
the key. Writes SHALL refuse stale/unsafe targets and preserve unrelated fields.

#### Scenario: Save then replace then clear
- **WHEN** the writer confirms Save to this project for a new key, later confirms Replace and then Clear saved key
- **THEN** only `api_key` changes on each successful operation, no old key is copied into input history/backups, and source/status refreshes without exposing a value
- **AND** clearing saved credentials leaves an active session override in force or exposes the environment fallback when no session is active

#### Scenario: Cancel or refuse unsafe persistence
- **WHEN** confirmation is declined, configuration changes externally before save, the destination/temp path is unsafe, or writing fails
- **THEN** no credential overwrite occurs, unrelated configuration survives, and an actionable sanitized error or cancellation is shown
- **AND** failed Save does not report persistence or implicitly activate the new key

### Requirement: Connection testing is explicit and non-generative
Test connection SHALL authenticate through the same effective credential
selection as generation, report success or sanitized failure, and make no
generation request or project write. Create/Open, key entry, activation,
Save/Replace/Clear and navigation SHALL make no implicit provider call.

#### Scenario: Test current credentials
- **WHEN** the writer explicitly chooses Test connection with an effective credential
- **THEN** one existing plan lookup runs on the cancellable worker, and the GUI reports connected, refused or stopped without revealing response secrets
- **AND** no model generation, `limits.json` save or accepted-content change occurs

#### Scenario: Missing key and busy test
- **WHEN** Test connection has no effective credential or is already running
- **THEN** missing-key guidance prevents a request or the existing one-operation gate prevents a second request
- **AND** Stop/close follows cooperative settlement and restores usable controls

### Requirement: Credentials cannot escape through generated or diagnostic output
Credential values from session, project and configured environment sources
SHALL be redacted from GUI results/events, errors, logs and provider echoes
before persistence or export. Credential storage SHALL be limited to explicit
project Save/Replace; defaults and distributed resources SHALL stay empty of keys.

#### Scenario: Synthetic secret echo coverage
- **WHEN** fake provider text, metadata, malformed chunks or exceptions echo distinct session/project/environment sentinels, including split streamed fragments
- **THEN** no sentinel appears in delivered events, visible output, stdout/stderr, call logs, limits metadata, generated artifacts or exported manuscript
- **AND** redaction does not expose headers, effective configuration or credential-bearing object representations

#### Scenario: Defaults remain independent of session or storage choices
- **WHEN** a writer uses or explicitly saves a synthetic key and then creates a different project
- **THEN** its bundled defaults and new `project.json` have empty `api_key` and no prior credential is copied
