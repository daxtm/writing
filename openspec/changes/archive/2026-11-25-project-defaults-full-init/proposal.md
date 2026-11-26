# Proposal

## Why

GUI Create currently leaves out the writer preset, so a new project still
requires an external file before drafting. CLI init duplicates the shared
initializer and neither uses the owner's selected nonsecret defaults.

## What Changes

- Fix shared CLI/GUI init to create every initial file/directory plus a usable
  bundled writer preset, using the owner's sanitized project defaults.
- Cover immediate and deferred GUI Create paths and copied-executable resource
  loading, without provider calls or a preset picker.
- Preserve existing files, configured external preset paths and create-missing-only
  retries; report collisions and partial failures truthfully.
- Bundle reviewed runtime defaults because existing init and explicit preset
  import cannot supply defaults when no external preset is selected.

## Capabilities

### New Capabilities

- `project-initialization`: complete, portable, nonsecret new-project defaults
  and shared non-overwriting initialization.

### Modified Capabilities

- `desktop-project-planning`: both GUI Create paths perform complete init;
  Open remains read-only.
- `standalone-distribution`: the copied executable contains the defaults and
  produces the same initialized files as source.

## Impact

Extends existing config, planning/init, CLI adapter, GUI Create and standalone
build/notices paths, with offline source/frozen/offscreen regression coverage.
No new dependencies. ADR-0010 records the distribution choice.

Out of scope: key entry, streaming, wizard/navigation, migration/reset of
existing projects, automatic bible/outline/scenes generation, limits fetching,
and shipping.

After implementation, run `uv run --script longform.py init ./demo`: `created:`
includes `writer_preset.json` alongside the five current files; seven initial
directories also exist. On Wayland, run
`QT_QPA_PLATFORM=wayland uv run --script longform.py gui ./gui-demo` and choose
Create: the same complete setup appears without a preset picker or API request.
