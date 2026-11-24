# ADR-0009: Bundle CLI and Qt workspace in the same executable

- Status: Accepted
- Date: 2026-11-23
- Related: standalone-gui; ADR-0006; ADR-0007; ADR-0008

## Context

The owner requests the GUI in the stand alone binary. ADR-0008 chose the
copyable Linux x86_64 glibc `dist/longform` built from the source launcher.
The existing build pins only the CLI dependency closure. The Qt workspace
on `feat/gui-wayland-shell` already supplies the writing interactions and
native-Wayland-only `gui DIR`; it is not yet part of this main baseline.
Packaging must reuse it, not create another interface or writing engine.

## Options

1. Extend the existing one-file console executable with the Qt workspace —
   one artifact and command surface, but every CLI user receives the larger
   bundle and pays its extraction cost.
2. Keep the CLI executable and distribute a separate GUI directory bundle —
   smaller CLI downloads and independently replaceable GUI libraries, but
   writers must copy a second, multi-file application rather than the
   requested existing standalone binary.

## Decision

Choose option 1. The deciding reason is that copying the same `longform`
executable must provide both existing CLI commands and `gui DIR` without
installing Python, uv, or Qt packages. Extend the existing build and pinned
closure, retaining console mode and the source launcher. Preserve lazy GUI
imports and the workspace's Wayland-only policy.

ADR-0008's native host/extraction boundary still applies; a Wayland compositor
and documented host libraries remain runtime prerequisites. This decision
does not establish plugin compatibility, satisfy redistribution obligations
merely by selecting one-file mode, or authorize release. Build-time inventory,
matching third-party notices, copied-binary tests, and separate real Wayland
acceptance must establish the actual boundary.

## Consequences

- Good: one executable and one project format serve CLI and desktop writers.
- Good: existing GUI operations, worker, and behavior remain the only GUI implementation.
- Bad: Qt increases artifact size, extraction/startup time, temporary storage,
  build time, and dependency-update responsibility even for CLI-only users.
- Bad: native plugins and their host-library dependencies need verification
  beyond an executable `ldd` report or headless CLI success.
- Bad: notices must cover bundled Qt/Shiboken components as well as Python
  distributions; any distribution needs the applicable upstream licensing
  materials and conditions, not an assumption that a notices file suffices.
- Bad: physical desktop acceptance cannot be replaced by offscreen widget tests.
