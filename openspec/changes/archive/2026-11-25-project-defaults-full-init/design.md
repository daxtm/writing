# Design

## Context

See `proposal.md` for motivation. Selection is the first unchecked item in the
guided-workflow roadmap on `docs/roadmap-guided-workflow`, read before
`ock branch feat/project-defaults-full-init` created this branch from
`origin/main`. That roadmap is not yet on this branch; this change carries
its selected contract, not proposals for the other roadmap items.

Relevant baseline:

- `planning_operations.INIT_FILES`/`INIT_DIRS` define five files and seven
  directories. `init_project` adds a preset only with `preset_src`.
- `commands.cmd_init` still duplicates file/directory/preset creation despite
  the shared operation. Fix that boundary, not another initializer.
- `MainWindow.create_project` and `_run_pending_action` both call
  `init_project` without a preset. The latter resumes a Create deferred behind
  a dirty-settings Save. Both must receive the same new default behavior.
- `Project` and settings operations merge `DEFAULT_CONFIG` into existing
  configurations; globally replacing those fallback values would alter old
  projects that omit fields.
- `scripts/build-standalone.sh` already freezes CLI/GUI and collects certifi
  data. The frozen-test freshness input list currently includes package Python
  files but not package JSON assets.
- Existing tests freeze the old five-file init transcript and the planning
  journey imports a preset after Create. These expectations must change
  deliberately, without weakening explicit import's no-overwrite rule.

`openspec/config.yaml`'s stale no-GUI context is corrected by this proposal;
the source baseline already has the Qt workspace and copied executable.

## Goals / Non-Goals

**Goals:** the three delta specs define observable behavior; ADR-0010 defines
the durable distribution policy. Keep one create-missing-only operation,
separate new-project defaults from existing-project fallbacks, and prove
source/frozen/GUI agreement without access to the private originals.

**Non-goals:** a general defaults management service, startup synchronization,
an installer, new preset semantics, changing model-call prompt/sampler code,
or supporting simultaneous project writers/multi-file transactions.

## Decisions

### 1. Bundle reviewed derivations, never private originals

Follow [ADR-0010](../../../docs/adr/0010-sanitized-new-project-defaults.md),
the same accepted decision already recorded on the roadmap branch. Reading
absolute source paths at runtime is rejected because copied binaries and clean
checkouts must work independently.

During implementation only, read these files without modifying them:

- `/home/daxtm/Documents/fuckpi/project.json`
- `/home/daxtm/Documents/fuckpi/56295265-LLam_ception-1.3.json`

Prepare application-owned JSON resources under `longform_core/resources/`:
`project_defaults.json` and `writer_preset.json`. The source project has the
current supported top-level configuration fields and the five current roles;
the preset has object-valued `instruct`, `context`, `sysprompt`, `preset`.
Only structural information was inspected for this proposal; no source values
or credentials are copied into these artifacts.

Copy supported nonsecret settings, preserving the selected models, sampler
values, preset overrides, prompt/template text, budgets and other supported
defaults, except the three forced fields in the spec. Keep `Untitled` unless
the initializer receives an explicit title. Validate the master export using
the existing rules and ensure the nested objects/fields needed by
`Project.preset`, `build_writer_prompt` and `writer_sampling` are usable.
Do not reinterpret unsupported sampler fields or change provider payload rules.

Review **every nested value**, including template text and metadata, for
credentials, auth/secret fields, local paths and private story content.
Discard unsupported credential/path metadata; redact private values rather
than mechanically copying the raw files. Review the final staged assets before
tracking. Document the source filenames, supported-field selection, forced
overrides, review outcome and any applicable source notices in
`docs/project-defaults.md`; include preset provenance/notices in the existing
standalone sidecar generation. Do not invent a third-party license or put the
originals in fixtures. Tests may inspect the approved public runtime assets;
they never read the originals.

No persistent exporter command/service is needed: implementation prepares and
reviews these two versioned resources once. Resource validation uses an
explicit approved-field schema recorded with the resources, not heuristic
scrubbing of arbitrary prompt text. Its tests use synthetic variants with
forbidden credential/path metadata and reject or exclude those fields without
echoing values. Private content in supported text fields requires the human
review above; no automated detector is claimed.

### 2. Scope selected defaults to new configurations

Load and validate the packaged defaults through a small helper beside the
existing config/init code, independent of cwd and without importing Qt.
Return a fresh copy per call so a title override or adapter edit cannot
mutate later projects. Missing/corrupt required assets produce a sanitized,
actionable init error, not an old-default fallback or network fetch.

Keep `DEFAULT_CONFIG` as the existing project's fallback contract and keep
`Project`/settings merges unchanged. Use the reviewed defaults only when
creating an absent `project.json`. This is preferable to replacing the
global constant because the latter would change effective models/budgets for
old sparse configurations without changing their bytes. Add an optional
`title` input to the shared initializer for the explicitly supplied-title
contract; current CLI/Create need no new flag, prompt or title dialog and
therefore initialize as `Untitled`. Existing Settings still edits titles.

### 3. Extend the existing initializer and validation

`planning_operations.init_project` remains the only initializer. Preserve the
existing templates, empty JSON formats and directory names, adding the missing
preset to complete setup. Reuse master-export parsing/validation with
`import_preset`; do not change the explicit Import action's refusal to replace
an existing preset.

Select a preset source **before** creating a missing preset: explicit
`preset_src` wins over the bundle. Validate/read the selected source before
its write; invalid explicit input never falls back to the bundle. A regular
existing destination is preserved; an explicit override attempt yields the
existing CLI-style not-overwritten warning rather than an import error.
Preserve `roles.writer.preset` in an existing config, even when it is external.
Filling a missing local `writer_preset.json` does not retarget that config.

Retain safe-root/target/temp-path checks; refuse symlinks and wrong-type
collisions without modifying their targets. Check cancellation between
paths and before commits. Use complete per-file writes; no partially written
preset is counted as created. Generalize partial-work reporting to all
initialization failures, including file inspection/write, directory creation,
preset validation/write and cancellation. Include created files/directories
and the failed path/boundary, without credential-bearing JSON or raw errors.
Retry fills missing paths; there is no destructive rollback.

### 4. Keep adapters thin and reports truthful

Replace `cmd_init`'s duplicate loop with the shared operation, preserving
`init DIR [--preset FILE]`, the `project:`, `created:` and `next:` output
structure, existing explicit-source validation and warning semantics.
The intentional transcript change is the added default preset in the created
list; failure diagnostics may add accurate partial-work details. Update the
affected init snapshots, not unrelated CLI transcripts.

Both immediate and deferred GUI Create keep the existing worker, dirty-form
Save/Discard/Cancel and selection lifecycle. Never use current-project
settings as defaults for a different target. Failed/cancelled dirty Save must
not dispatch the deferred Create. Bind the new root only on successful init;
partial failure/Stop leaves the previous usable project selected and reports
what exists at the target. Update result presentation so the preset is not
omitted/double-counted or misleadingly described as an explicit import.
Open remains read-only, including for partially initialized projects.

### 5. Extend packaging and checks, not distribution architecture

Extend the existing standalone build's package-data collection to include only
the reviewed resources; do not add dependencies or require an adjacent asset
directory. Source and frozen init use the same packaged-resource helper.
Extend the sidecar notice generator and `docs/standalone.md` for the bundled
preset. Include these resource files in the existing frozen-test stale-build
input calculation so editing defaults cannot reuse an obsolete binary.

Extend the current suites rather than create another test runner:

- `tests/test_planning_ops.py`: fresh output, optional title isolation,
  exact supported defaults, legacy sparse-config fallback stability,
  repeated init, override precedence/validation, external paths, safe-path
  collisions, failure/cancellation/partial reporting.
- Existing CLI init tests: final transcript, missing destinations, explicit
  override warnings/errors and shared-operation delegation.
- `tests/qt_widget_cases.py` via `tests/test_qt_cases.py`: immediate Create,
  deferred Create after Save, failed/stale/cancelled Save, cancelled selection,
  partial init and read-only Open; register every added case. Update the
  Create-to-scene journey to expect a bundled preset and separately retain
  synthetic import success on an absent destination and refusal when present.
- `tests/test_standalone.py`: actual copied executable, unrelated cwd/path
  with spaces, no Python/uv on PATH or display, and existing native network
  guard. Compare six-file contents, seven directories, transcripts,
  idempotence and synthetic explicit overrides with source.

Tests/builds run with original paths unavailable; use read guards on the
exact named originals, never rename or modify those files. Keep test project
content and credentials synthetic. Missing/corrupt resource tests fail closed.
`scripts/check.sh` must discover and run all of this through its current
standalone and source stages, with no silent skip or network exemption.

## Risks / Trade-offs

- [A prompt/metadata field hides private content] → recursive human review of
  derived assets plus synthetic exclusion/regression checks; never log raw
  sources or commit their credentials. Automated schema validation alone is
  not evidence of sanitization.
- [New defaults alter old sparse projects] → separate init-only defaults and
  regression-test effective old fallback values as well as saved bytes.
- [Bundled preset makes existing import fixtures collide] → deliberately
  test both present/absent destinations; do not remove no-overwrite protection.
- [A frozen test passes using stale or checkout-adjacent data] → include JSON
  inputs in freshness checks and exercise the actual copied executable alone.
- [Init fails after writing earlier paths] → report partial completion and
  preserve completed work; there is no all-or-nothing transaction.
- [Offscreen passes are mistaken for desktop acceptance] → record a separate
  Wayland Create/reopen/dirty-Save walkthrough; mark it PENDING if unavailable.
  Do not claim the guided workspace complete or authorize shipping.

## Migration Plan

No existing project is migrated, rewritten or automatically repaired. New
initialization uses versioned reviewed resources; explicit repeated init only
fills missing paths. Deployment is the ordinary source update/rebuild, not
source-file discovery on the user's machine. Rolling back code/defaults affects
future initialization only; never delete created projects or presets to roll
back. Record implementation checks and actual/pending Wayland acceptance in
this change's `evidence.md`.

## Open Questions

None affecting implementation. Exact resource-loading internals remain an
implementation choice constrained by the source/frozen tests; no new dependency
or external API/version decision is required.
