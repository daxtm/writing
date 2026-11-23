# Design

## Context

See proposal.md for motivation. Main has no GUI. The launcher declares only
`httpx>=0.27`; `cli.main` constructs `Project` for every non-init command.
`Project` is unsuitable as the reading boundary because the pending reader
deliberately avoids credentials, provider setup, fatal CLI exits, and arbitrary
configuration exposure.

Reviewed reader baseline: `feat/reader-gui` at
`a1245dcc5e94881b657f4064f7dbb314466d69b7`, specifically
`longform_core/reader_model.py`, `tests/reader_support.py`,
`tests/test_reader_model.py`, and ADR-0005. Its snapshots already supply
allowlisted configuration, ordered current cards, all direct safe trees,
retained trees, node metadata/history, notes, partial totals, and safe cached
refresh. They do not yet expose tree-level steering or authorize writes.
The existing `Tree` and CLI `s`/`se` commands already persist `Tree.d["steer"]`;
reuse that format and `Tree.save`, not a separate steering file.

The owner verified `uv run --with 'pyside6>=6.7'` resolving PySide6 **6.12.0**:
a minimal QApplication with explicit Wayland reported platform `wayland`,
1920×1080, DPR 1.0, without XWayland. This establishes runtime feasibility,
not acceptance of this window, all compositors, themes, or scaling modes.

## Goals / Non-Goals

**Goals:** Qt presentation over the existing safe reader; one narrow steering
write boundary; deterministic selection/dirty-state preservation; observable
native startup diagnostics and offscreen coverage.

**Non-goals:** no generation, acceptance, asynchronous worker, cancellation,
provider integration, generalized operation framework, or Tk migration layer.
Reading a saved candidate is not previewing newly generated output.

## Decisions

### Reuse the reader model; replace only presentation

Implement [ADR-0006](../../../docs/adr/0006-wayland-writing-workspace.md);
respect the incremental boundary in
[ADR-0007](../../../docs/adr/0007-shared-writing-operations.md).
These accepted ADRs already cover the durable choices; no new ADR is needed.

Copy the three named model/test files from the recorded reader revision, then
make the smallest tested changes for tree-level steering and read baselines.
Do not merge/cherry-pick the entire Tk change, import its UI, or replace its
safety tests. Extend fresh-interpreter import tests to forbid both Tk and
PySide6. Preserve the historical ADR-0004/0005 records when integrating their
reader baseline: copy their existing bodies, restore their index rows, and mark
ADR-0005 superseded by ADR-0006 as ADR-0006 instructs. Do not revive either old
reader proposal or claim that its Tk implementation shipped on main.

Keep `reader_model` Qt-independent; add a small Qt-independent steering adapter
(e.g. `scene_steering`) using the existing safe-root/ID rules and `Tree`
persistence. GUI widgets consume sanitized snapshots/results, never raw project
configuration. Alternative: using `Project` throughout would undo privacy/error
boundaries; a second reader would duplicate tested loading semantics.

### One Qt Widgets window, with no drafting execution yet

Use a `QMainWindow`, horizontal splitter, scene/branch tree navigation, and a
right-hand reading/editor region. Scene cards retain chapter/file order;
retained trees are a separate read-only group. All saved nodes appear with
active-head/path markers; selecting one displays its text, metadata/history,
parent/children links, without changing the accepted head.

Provide Manuscript, Saved candidate/Branches, and Notes tabs. Notes expose all
supported sources/backups. Plain-text read-only panes retain literal markup.
A multiline steering editor below the reader has an explicit dirty indication,
Save steering (primary/default action outside multiline typing), Clear, and
disabled Generate with explanatory text. Enter in the steering editor inserts
a newline; it must not accidentally trigger Save. A status/error area remains
visible. Include explicit Refresh and prose size controls.

Use system palette roles rather than hard-coded light backgrounds, consistent
layout margins/spacing, system UI fonts, and an adjustable prose font size.
Maintain a useful tab order and visible focus; controls/panes must resize rather
than clip at ordinary window sizes. Read-only panes remain selectable/copyable.
No settings database or persisted font/layout preferences is required here.
Alternative: retaining Tk widgets or embedding a terminal contradicts ADR-0006.

### Steering writes are narrow and stale-aware

Add allowlisted tree-level `steer` (string, missing means empty) to snapshots.
Keep node-level recorded `steer` distinct. Invalid non-string tree steering
warns and disables editing rather than silently replacing malformed data.
The controller keeps selected current scene ID, saved steering, editor text,
dirty flag, and an opaque baseline of relevant scene-card identity and exact
tree source bytes/absence from when editing began. Baselines are internal, not
displayed raw configuration. Refresh must not advance a dirty editor's baseline.

Before Save/Clear, revalidate that the selected current scene still exists with
the same card, its ID/path is safe, no component below the canonical root is
symlinked, and the tree bytes/absence still match. Read the tree freshly and
modify only its top-level `steer`, preserving every unknown field, node,
counter, head, and metadata. Use `Tree` with a minimal safe path adapter, not
credential-loading `Project`. For an absent tree on a valid current card, use
the existing default `{"nodes": {}, "head": null, "counter": 0}` before saving.
Do not create other sources or initialize an absent project. Validate existing
tree shape sufficiently to reject damaged trees before exposing write controls.
Retained trees are always read-only.

Save stores exact editor text including newlines/whitespace; Clear attempts
the same operation with `""`, replacing editor text only after success.
On errors retain the original editor buffer/dirty state; report sanitized
relative-source diagnostics, never raw exception/configuration contents.
On a stale baseline offer **Reload saved steering / Keep editing**; only the
former deliberately discards local text and adopts the new baseline. No
automatic retry or silent field merge. Revalidate paths immediately before
save; concurrent writers/TOCTOU are not made atomic by these checks.

For scene changes or close, resolve dirty state with Save/Discard/Cancel;
failed Save behaves like Cancel plus an error. Same-scene tab/node selection
does not prompt. Until Save succeeds, selection changes must not bind the
editor to a different scene. Clear is explicitly labeled as saving an empty
note, not merely clearing an unsaved buffer.
Alternative: rewriting trees from display snapshots would lose unknown fields;
blind whole-tree saves would overwrite external work.

### Refresh updates views, not the owner's editing session

Use the Qt event-loop timer at approximately 2000 ms to call the model with a
reused `SourceCache`; explicit Refresh uses `force=True`. Keep refresh and local
steering I/O on the GUI thread for this small shell; no background worker is
introduced. After Save, force a snapshot reload and adopt its new clean baseline.

Separate view state (scene/tree ID, node ID, tab, pane scroll positions, editor
cursor/selection and focus) from snapshots. Reconcile by stable IDs, update only
changed panes, restore valid scroll positions (clamp only if content shrank),
and never reassign text/cursor in a dirty editor. Clean steering can follow
external updates; dirty steering remains with its original baseline and a
stale-source indication. Removed nodes remain explicitly unavailable until
the owner selects another; removed dirty scenes retain the text with writes
disabled. Invalid required configuration during refresh retains the last
snapshot labeled stale and disables writes until recovery. Unchanged refresh
must not repeatedly popup warnings or steal focus.

The controller's selected scene/editor state and the disabled Generate slot are
the seam for `gui-steered-drafting`. That change will capture/save steering and
add shared draft operations and its single worker; no speculative worker API
or provider dependency is needed now.
Alternative: rebuilding all widgets every tick loses scroll/focus and risks
overwriting dirty text.

### Lazy startup, native Wayland only, useful failure output

Add `gui` argparse dispatch **before `Project(args.dir)`** and lazily import the
GUI entry point there. Importing the launcher, non-GUI commands, models, or
`--help` must not import PySide6/Tk or start QApplication. Keep the launcher thin.

For the public GUI command, unset `QT_QPA_PLATFORM` means set it to `wayland`;
if set, accept exactly `wayland`, not `xcb`, `offscreen`, or fallback lists.
Widget tests instantiate the window directly offscreen, not through this
production-platform gate. After application initialization verify/report
`platformName() == "wayland"` before showing a project window; fail otherwise.
Do not mutate the selection to another platform on error.

Handle missing PySide6/imported system libraries with concise actionable stderr.
Because platform initialization may fail below ordinary Python error handling,
emit and flush a short startup guidance line **before QApplication construction**:
native Wayland is required; on failure check the Wayland desktop/session/socket
and Qt Wayland/system libraries, then retry the explicit uv command. Keep native
Qt failure stderr alongside this guidance. This ensures even an initialization
abort has recovery advice; do not promise every plugin failure becomes a Python
exception. No probe service, subprocess launcher, or second runner is needed.
Do not log credentials/project configuration or raw Python tracebacks.

### Dependency provisioning and test isolation

Add `pyside6>=6.12.0,<6.13` to the launcher's PEP 723 dependencies beside httpx.
6.12.0 is the verified resolution; the range bounds future updates to that minor
series, not a claim all future patches were tested. Record the resolved runtime
in acceptance and rerun desktop checks if it changes. Lazy import avoids GUI
startup, **not** uv download/installation costs for CLI-only users.

Extend the existing `scripts/check.sh` test command to:

```sh
uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' pytest -q tests
```

Use a normally collected wrapper test to launch explicit Qt case files in the
same installed interpreter with `QT_QPA_PLATFORM=offscreen`; the child case file
must not also be automatically collected in the parent (for example,
`tests/qt_widget_cases.py`). Inherit the existing subprocess network guard,
credential removal, repository import path, bounded timeout, and failures.
Missing Qt or child test failure fails the wrapper; never use `importorskip`.
Model/CLI tests stay independent of Qt/display, with fresh-process import-block
assertions. No new check script, dependency manager, network allowance, or
display-conditional skip. Dependency installation may access the network; tests
themselves may not. Existing CLI outputs/prompts/trees remain regression-tested.

## Risks / Trade-offs

- Large Qt dependency even for CLI-only help → accepted in ADR-0006; document
  clean-checkout download/disk costs in AGENTS and run instructions.
- Synchronous snapshot loading may pause on unusually large projects → retain
  cache and changed-pane updates; do not introduce the next change's worker.
- A stale-source check is not a lock/transaction → reject known conflicts and
  document simultaneous CLI/GUI writing as unsupported.
- Offscreen tests cannot establish compositor integration → perform the separate
  real desktop acceptance below; missing hardware coverage is explicitly recorded.
- The verified minimal app does not cover all Linux plugin failures → preserve
  actionable pre-start advice and native Qt stderr, and test forced failures.

## Migration Plan and Acceptance

No project format migration: this writes the CLI's existing tree-level field.
Copy only the reader model/tests and historical decision records, add Qt shell
and dependencies, then update AGENTS layout/check/run facts and the selected
roadmap item's status only after implementation is verified. Keep milestone 1
unchecked while `gui-steered-drafting` is outstanding.

First test commit demonstrates missing visible behavior before implementation:
offscreen window opens, saved inactive prose/notes are selectable, Save persists
steering, and the command blocks until close. Follow with focused model,
dirty-state, refresh, failure, and CLI parity tests. No provider fake is needed
to implement a shell that never calls a provider; existing network refusals prove
that constraint.

Real desktop acceptance, separate from `./scripts/check.sh`:

1. Use a temporary synthetic project built with `tests/reader_support.py`:
   two current scenes, active and inactive nodes, retained tree, and all notes.
2. Run `QT_QPA_PLATFORM=wayland uv run --script longform.py gui DIR`.
   Record compositor/distribution, resolved PySide6/Qt versions, reported
   platform, screen/DPR, and command exit on close.
3. Verify one window, resize/splitters, all-branch/notes navigation, literal
   read-only prose, primary Save, Clear/reopen persistence, and all three dirty
   scene-switch/close choices. Exercise refresh during typing/scrolling.
4. Check light/dark contrast, keyboard focus and multiline entry, clipboard
   copy/paste, adjustable prose size, 100%/200% and available fractional/
   mixed-monitor scaling. Record unavailable modes, not an invented pass.
   File dialogs are **not applicable in this shell**, which opens DIR only.
5. Launch without a Wayland session and with invalid platform configuration;
   verify actionable failure with no alternate-platform window.

Rollback removes the new command/dependency and Qt modules; existing tree
steering stays CLI-compatible. No project files need reverting.

## Acceptance Record

Recorded on 2026-11-23 on the implementation branch (`feat/gui-wayland-shell`),
session: KDE Plasma 6.8.3 on KWin 6.8.3, `XDG_SESSION_TYPE=wayland`,
`WAYLAND_DISPLAY=wayland-1`, three screens, primary 1920×1080 at DPR 1.0
(physical 531×299 mm). Resolved runtime: **PySide6 6.12.0 / Qt 6.12.0** via the
declared `pyside6>=6.12.0,<6.13` range. Synthetic project built with
`tests/reader_support.py` (two current scenes with active + inactive nodes, a
retained tree, bible/state/checks/critiques including a backup).

Verified programmatically on the real Wayland display (no XWayland):

- The actual entry point `QT_QPA_PLATFORM=wayland uv run --script longform.py
  gui DIR` printed the flushed pre-start guidance on stderr before
  QApplication, then reported `Qt platform 'wayland', PySide6 6.12.0,
  Qt 6.12.0` and blocked until the process was signalled (window lifetime).
- One `MainWindow` instance only; `windowHandle().isVisible()` under a native
  Wayland window; clean programmatic close → `app.exec()` returned 0 (exit 0).
- Reading: inactive saved node, retained tree, notes (bible, critique backup)
  selectable and literal; programmatic clipboard copy from the read-only pane
  returned the pane text (`QClipboard.text()`).
- Steering: multiline Save persisted exactly (`Wayland acceptance direction.\n
  Second line.`) with head/nodes/counter unchanged; a second window (reopen)
  showed the same steering.
- Refresh: an external `bible.md` edit appeared after explicit `Refresh` with
  selection/tab preserved.
- Failure launches: with `WAYLAND_DISPLAY`/`DISPLAY` removed the command
  exited 134 after printing the flushed recovery guidance and the native Qt
  plugin error (`Could not load the Qt platform plugin "wayland"`); with
  `QT_QPA_PLATFORM=xcb` it exited 1 with the explicit no-fallback diagnostic
  and opened no window.

Not verified here — left for the owner's interactive desktop acceptance:
mouse-driven resize/splitter dragging, real keyboard traversal (Tab focus
walk, Enter typing), system light/dark theme switching, 100%/200% and any
fractional or mixed-monitor scaling (only DPR 1.0 was observed), clipboard
paste into another application, and closing via the compositor's window
button (close was programmatic). Offscreen CI/widget tests do not count as
compositor integration. File dialogs are **not applicable** in this shell,
which opens DIR only.

## Open Questions

No implementation-blocking decisions. The acceptance record must identify the
owner's compositor/distribution and available scaling setups; system fonts and
palette are the default until a visual preference is supplied.
