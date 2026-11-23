## Purpose

Let a writer continuously read saved project material and every draft branch in a local browser without issuing terminal reading commands.

## ADDED Requirements

### Requirement: Start and stop a local reader
The CLI SHALL provide `view DIR [--port N] [--no-browser]`, bind only to
`127.0.0.1`, print the bound URL, and serve until Ctrl-C. The default port SHALL
be 0 (automatically assigned); explicit ports SHALL be integers from 0 to 65535.
It SHALL attempt to open the default browser unless suppressed.

#### Scenario: Start without a browser
- **WHEN** `view DIR --port 0 --no-browser` starts for a valid project
- **THEN** stdout includes `Reader: http://127.0.0.1:<assigned-port>/` after binding
- **AND** the listener address is `127.0.0.1`, the assigned port is nonzero, and no browser is opened
- **AND** Ctrl-C closes the listener and exits without a traceback

#### Scenario: Browser attempt and unavailable browser
- **WHEN** `view DIR` starts and the default browser is available or reports failure
- **THEN** one browser-open attempt uses the printed URL
- **AND** browser failure leaves the reader running and the URL available for manual opening

#### Scenario: Invalid startup
- **WHEN** the directory lacks a valid project configuration, a port is invalid, or the requested port is occupied
- **THEN** the command exits nonzero with a concise error, without a traceback, browser launch, or successful-reader URL

### Requirement: Overview reflects active writing progress
The overview at `/` SHALL show title, project target and actual word counts, and
scene links with IDs, titles, statuses, targets, and actual counts. Actual counts
SHALL match existing active-chain word counting, not all generated branches.
Retained trees without current scene cards SHALL also be linked and labeled,
but excluded from current-project totals.

#### Scenario: Mixed active and inactive writing
- **WHEN** the overview is requested for a project with active branches, inactive swipes, an empty scene, and a retained tree absent from scene cards
- **THEN** it lists every current scene and the retained tree
- **AND** actual counts include only active text of current scenes, with zero for the empty scene
- **AND** the retained tree is labeled as having no current scene card

### Requirement: Every saved branch is readable
Each `/scenes/<scene-id>` page SHALL show active manuscript text and every
persisted node, including inactive swipes and branches. It SHALL identify the
head and active path, expose parent/child jumps, and show full node text, ID,
parent, source, model, creation time, word count, steering note, and ended/trimmed
flags. Missing optional metadata SHALL be labeled unavailable; saved edit-history
text SHALL also be readable.

#### Scenario: Navigate an inactive branch
- **WHEN** a scene with an active chain and multiple inactive siblings and descendants is opened
- **THEN** active text matches the CLI tree text, including continuation separators
- **AND** every saved node's untruncated text and metadata are present, including edited text history
- **AND** parent/child links target node anchors, and the head and active nodes are distinguished

#### Scenario: No accepted candidate
- **WHEN** a scene has saved candidate nodes but no active head
- **THEN** active text is labeled empty and every saved candidate remains readable

### Requirement: Supporting writing is readable as plain text
The `/notes` page SHALL show bible, continuity state, detailed/brief scene
summaries, arc summaries with ranges, and every saved Markdown check and critique
including previous reports. Absent optional content SHALL be labeled empty.
Writing SHALL retain paragraph breaks without interpreting Markdown or HTML.

#### Scenario: Read supporting material
- **WHEN** `/notes` is requested with distinctive text in each supported source and a previous critique
- **THEN** every source's full text is present under a recognizable heading or filename
- **AND** missing optional sources have an empty-state label rather than an error

### Requirement: Saved changes refresh without losing reading position
Pages SHALL check for saved changes every two seconds without manual reload.
Changed content SHALL update while preserving scroll position and the node
fragment. Each response SHALL use fresh disk content and disallow caching.
The reader SHALL NOT require the writer to export a manuscript or stream unsaved tokens.

#### Scenario: Draft saves another swipe
- **WHEN** a new node is saved after a scene page has been fetched and the next refresh request occurs
- **THEN** the response includes the new node without restarting the reader or exporting
- **AND** the page's refresh behavior preserves the existing scroll position and fragment

#### Scenario: Temporary unreadable file recovers
- **WHEN** a required JSON file is malformed or a needed source cannot be read during a request
- **THEN** the response is 503 with a generic retry message, no raw file content or traceback, and automatic retry remains enabled
- **AND** the next request succeeds once the valid readable file is restored

### Requirement: Serve only escaped allowlisted writing
The reader SHALL escape all project-controlled strings in HTML and attributes.
Only title and target word count from configuration SHALL be exposed; all other
configuration fields, credentials, presets, and logs SHALL NOT be served.
Unknown routes, unsafe paths, and symlinked content SHALL return 404.
Errors SHALL NOT disclose configuration, absolute filesystem paths, or raw inputs.

#### Scenario: Markup and credentials remain inert or private
- **WHEN** supported content contains `<script>`, quotes, ampersands, and an image event handler, while configuration contains synthetic secrets and extra fields
- **THEN** writing is returned as escaped text, not executable project-supplied markup
- **AND** no response body or header exposes the synthetic secrets or extra configuration values

#### Scenario: Reject filesystem probing
- **WHEN** GET requests target `/project.json`, `/calls.jsonl`, `/trees/s01.json`, unknown scenes, `../`, encoded or double-encoded traversal, backslashes, or a symlinked supported file or directory
- **THEN** each receives 404 without disclosing the requested file's contents or absolute path

### Requirement: Requests cannot mutate the project
The reader SHALL provide only read-only GET routes, without directory listings,
file downloads, write operations, external assets, or API/provider calls.
Non-GET methods SHALL return 405. Requests with a Host other than the printed
loopback authority SHALL return 403, without enabling cross-origin access.

#### Scenario: Reject writing and foreign hosts
- **WHEN** POST, PUT, PATCH, DELETE, HEAD, or OPTIONS requests target a valid route, or a GET supplies a foreign Host
- **THEN** non-GET requests receive 405 and the foreign-Host GET receives 403
- **AND** no project file is created, changed, or deleted and no external request occurs
