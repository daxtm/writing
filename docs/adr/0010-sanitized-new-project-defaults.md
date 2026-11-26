# ADR-0010: Bundle sanitized owner defaults for shared project initialization

- Status: Accepted
- Date: 2026-11-23
- Related: docs/ROADMAP.md guided workflow milestone 1; project-defaults-full-init; ADR-0007; ADR-0008

## Context
The owner selected an external project.json and SillyTavern master-export
preset as defaults for all new projects, excluding their API key. Shared
`planning_operations.init_project` already creates five files and seven
directories, but imports a preset only when supplied explicitly. GUI Create
calls that operation without a preset. Source and frozen execution must work
without the owner's home directory, while existing projects remain untouched.

## Options
1. Read the selected absolute paths whenever init runs — automatically follows
   local edits, but fails on other machines and risks copying a credential.
2. Bundle reviewed, sanitized application defaults and initialize from them —
   portable and reproducible, but updates require reviewing assets and rebuilding.

## Decision
Choose option 2 because new projects must be usable without the owner's files.
Extend existing DEFAULT_CONFIG/init/preset validation and frozen resource
packaging; do not create a separate GUI initializer or defaults service.
Derive supported nonsecret settings from the selected source once during
implementation, force an empty api_key and the FEATHERLESS_API_KEY variable
name, and use project-relative writer_preset.json. Bundle the validated,
reviewed writer master export as a runtime resource, not a private fixture.
Retain other supported model, sampler and prompt defaults from the sources.

CLI init and every GUI Create path create all existing init paths plus the
default preset without provider calls. Explicit CLI --preset takes precedence
for an absent preset destination. Preserve create-missing-only behavior,
existing preset files/configuration and truthful partial-failure reporting.
No runtime/build/test access to the original absolute paths is permitted.

## Consequences
- Good: new projects work identically in source and copied-executable runs,
  without manually finding a preset or exposing an owner's credential.
- Good: one initializer retains validation and non-overwrite guarantees.
- Bad: the selected preset becomes a maintained distribution asset requiring
  provenance/notices and review of nested values before committing; the raw
  private source remains untracked.
- Bad: changing the owner's source files does not update shipped defaults;
  changing defaults deliberately affects new-project regression expectations.
