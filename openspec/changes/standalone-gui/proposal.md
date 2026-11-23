# Proposal

## Why

Implement the GUI into the stand alone binary so writers can open the same writing workspace without installing Python, uv, or PySide6. The existing build freezes only the CLI dependency closure, while the implemented Qt workspace lives on `feat/gui-wayland-shell`, not this branch's main baseline.

## What Changes

- Extend `scripts/build-standalone.sh` and its pinned requirements to bundle the existing GUI, PySide6/Shiboken, Qt libraries, and native Wayland plugins in the same `dist/longform`.
- Keep existing CLI commands; add the source workspace's `gui DIR` command to the frozen executable with identical controls and project files.
- Preserve native-Wayland-only startup and give frozen users recovery instructions that do not require uv or source.
- Extend existing copied-binary tests, compatibility metadata, notices, and `docs/standalone.md`; require separate frozen-binary Wayland acceptance.

This fixes the existing distribution path rather than adding a second builder or GUI: its current requirements omit Qt, and main has no GUI source to freeze. Implementation depends on the existing Qt workspace being integrated first; this proposal neither merges branches nor reimplements that workspace.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `standalone-distribution`: include the existing GUI in the executable, preserve CLI behavior, and verify/document the frozen Qt runtime.

## Impact

Build requirements/script, startup diagnostics, frozen tests, check entry point, and distribution documentation. ADR-0009 records the single-artifact decision.

**Out of scope:** new GUI features, changing prompts/files, installers, desktop launchers, other platforms, XWayland fallback, release/shipping, or completing unrelated workspace acceptance.

**See it work after implementation:** build, copy only `dist/longform` elsewhere, then run `QT_QPA_PLATFORM=wayland /absolute/path/longform gui /path/to/project`. Expect the existing native window; saved steering and exported prose remain visible to the CLI.
