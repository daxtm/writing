# Decision log (ADRs)

One decision per file, `NNNN-kebab-title.md`, from [0000-template.md](0000-template.md). Written by OpenCode
when a decision outlives one change (a dependency, a data format, an architecture choice); routine
choices stay in the OpenSpec change's `design.md`. Merging the PR accepts it. Never edited afterwards,
except to mark it superseded by a newer ADR.

| ADR | Title | Status | Date |
|---|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted | 2026-11-23 |
| [0002](0002-single-file-cli.md) | Keep the single-file CLI through the prototype | Superseded by ADR-0003 | 2026-11-23 |
| [0003](0003-split-into-package.md) | Split the CLI into a package now | Accepted | 2026-11-23 |
| [0004](0004-local-web-reader.md) | Use a read-only standard-library local web reader | Superseded by ADR-0005 | 2026-11-23 |
| [0005](0005-desktop-gui.md) | Use Tkinter and ttk for the native read-only desktop reader | Superseded by ADR-0006 | 2026-11-23 |
| [0006](0006-wayland-writing-workspace.md) | Use Qt Widgets for the Wayland writing workspace | Accepted | 2026-11-23 |
| [0007](0007-shared-writing-operations.md) | Share writing operations between CLI and an asynchronous GUI | Accepted | 2026-11-23 |
| [0008](0008-standalone-native-executable.md) | Distribute a frozen native executable alongside the source launcher | Accepted | 2026-11-23 |
| [0009](0009-single-cli-gui-executable.md) | Bundle CLI and Qt workspace in the same executable | Accepted | 2026-11-23 |
| [0010](0010-sanitized-new-project-defaults.md) | Bundle sanitized owner defaults for shared project initialization | Accepted | 2026-11-23 |
| [0011](0011-gui-project-credentials.md) | Enter project credentials in the GUI using existing storage | Accepted | 2026-11-23 |
| [0012](0012-shared-generation-stream-events.md) | Deliver all generated answers through shared preview events | Accepted | 2026-11-23 |
| [0013](0013-cpython-minor-runtime-pin.md) | Pin the CPython minor and accept patch updates automatically | Accepted | 2026-11-25 |

ADR-0004/0005 are the reader-baseline decisions integrated from the
`feat/reader-gui` branch; ADR-0006 supersedes 0005's Tk presentation choice for
the expanded workspace.
