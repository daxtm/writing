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
| [0006](0006-wayland-writing-workspace.md) | Use Qt Widgets for the Wayland writing workspace | Accepted | 2026-11-23 |
| [0007](0007-shared-writing-operations.md) | Share writing operations between CLI and an asynchronous GUI | Accepted | 2026-11-23 |
| [0008](0008-standalone-native-executable.md) | Distribute a frozen native executable alongside the source launcher | Accepted | 2026-11-23 |

Numbers 0004 and 0005 are allocated to the browser/desktop-reader decisions on
the unmerged `feat/reader-gui` branch. Preserve those records when integrating
it; 0006 replaces 0005's presentation choice for the expanded workspace.
