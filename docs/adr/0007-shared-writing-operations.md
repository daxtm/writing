# ADR-0007: Share writing operations between CLI and an asynchronous GUI

- Status: Accepted
- Date: 2026-11-23
- Related: docs/ROADMAP.md GUI milestone 1; gui-steered-drafting; ADR-0003; ADR-0006

## Context
Existing `cmd_*` functions already implement planning, drafting, continuity,
review, and export. They mix reusable `Project`/`Tree`/`Lore`/prompt/API work
with terminal input, `$EDITOR`, printing, candidate selection, and file saves.
The GUI must expose those same choices without terminal prompts, duplicate
writing rules, or blocking its event loop during network operations. Existing
prompts, history, branch acceptance, and files must remain compatible.

## Options
1. Drive CLI subprocesses and parse their terminal conversation — retain the
   entry points, but couple buttons to prompts, ANSI output, external editors,
   and an undocumented interactive protocol.
2. Extract shared UI-independent operations incrementally — retain the CLI as
   an adapter and call the same operations from a background GUI worker, but
   change tested orchestration boundaries and introduce explicit result/error
   and lifecycle handling.

## Decision
Choose option 2. The deciding reason is preserving one source of writing
behavior while presenting author choices directly in both interfaces. Do not
automate stdin, monkeypatch terminal/editor helpers at runtime, add a local
HTTP service, or rewrite all commands before the first working button.

Extract only the operation required by the next control, starting with draft
generation and acceptance. Inputs include the selected scene/head, steering,
and relevant project content; results/events expose progress, candidate IDs,
warnings, previews, and failures without requiring Qt or terminal output.
Keep prompt construction, cleaning, and persistence in the existing core.
CLI adapters preserve their transcript and editor choices behind parity tests.
The GUI presents editing/acceptance decisions between operations, not by
blocking a worker waiting for a modal terminal interaction.

Use one background worker for one active project operation, with queued Qt
signals for progress/results; only the GUI thread changes widgets. Existing
`Api.many` may still use its bounded internal concurrency. Do not add a durable
job database, multiple simultaneous project writers, or a second async network
stack. Capture inputs before starting; before any write detect changed source
content and require reload/retry instead of overwriting externally modified
files. This detects stale inputs, not an atomic cross-process transaction;
simultaneous CLI/GUI writing remains unsupported.

Cancellation is cooperative: expose Stop, check a cancellation token at stream
chunks and operation/save boundaries, and let an outstanding network wait reach
its configured timeout if needed. Do not terminate threads forcibly. Retain
completed saved candidates and prior edits, discard partial streamed text, and
do not move the accepted head on failure or cancellation. Closing during work
offers Stop and wait or Keep open; shutdown completes only after the worker
settles. Refresh never silently replaces dirty editor contents.

## Consequences
- Good: CLI and GUI share prompts, branching semantics, persistence, and offline
  fake-provider tests rather than accumulating divergent implementations.
- Good: a responsive reader can show progress while author-controlled preview
  and acceptance remain explicit steps.
- Bad: incremental extraction touches delicate orchestration and needs
  transcript/prompt/file parity tests before each affected CLI path changes.
- Bad: cooperative cancellation is not instantaneous; a blocked request may
  delay closing until its configured timeout, and already saved work is not
  rolled back.
- Bad: serial execution and stale-input detection restrict concurrent editing;
  existing multi-file saves are not made transactional by this decision.

Reference:
- [Qt worker objects and queued cross-thread signals](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html).
