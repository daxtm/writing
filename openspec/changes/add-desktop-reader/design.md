# Design

## Context

See [proposal.md](proposal.md) for motivation and
[desktop-reader/spec.md](specs/desktop-reader/spec.md) for behavior.
`cli.main()` dispatches `init` before constructing `Project`; use that existing
boundary for `gui`. `Project` loads merged configuration, including credentials,
and `utils.read_json()` calls `die()` on bad JSON, so neither is appropriate for
an independently recoverable reader. Do not alter their existing CLI behavior.

`Tree.d` contains all saved nodes, the current head, and node history.
`Tree.text()` owns continuation/separator rules; `utils.words()` owns counts.
Scene regeneration retains old `trees/*.json`, which must not disappear from
the reading index. Existing saves already use temporary files and `os.replace`.
`scripts/check.sh` already discovers `tests/`; the existing network guard stays
closed, including loopback. No server exception or new check runner is needed.

The owner verified Tk 9.0.4 under uv-managed Python 3.13 with a desktop display;
system Python lacks Tk libraries. This proposal adds no runtime dependencies.

## Goals / Non-Goals

**Goals:** preserve the launcher, file formats, current CLI behavior, tree text
semantics, and offline checks; separate safe data loading from desktop widgets.

**Non-Goals:** see proposal scope. No general persistence refactor, file chooser,
watcher dependency, worker-thread framework, rich-text renderer, or web fallback.
Read persisted content only; deleted nodes and unsaved tokens cannot be recovered.

## Decisions

### Native desktop architecture and CLI boundary

Adopt [ADR-0005](../../../docs/adr/0005-desktop-gui.md), superseding ADR-0004.
Use Tkinter plus ttk, not a browser wrapper or an external desktop toolkit.
Delete the unimplemented `add-reader-gui` change; git history and superseded
ADR-0004 retain the rejected plan, not an archive suggesting delivery.

Add `gui DIR` using existing argparse helpers; dispatch before `Project` as
`init` does, with a lazy import of `gui.launch(dir)`. No GUI imports/re-exports
in the thin launcher or ordinary help path. `launch` safely loads the initial
snapshot, constructs one root/app, and runs `mainloop()` until close.
It returns normally after close; command-boundary handling converts missing Tk,
display startup failure, and invalid required configuration into concise nonzero
errors without raw exceptions or input. Missing runtime support points to
`uv run --script longform.py gui DIR` and a working desktop display. No automatic
dependency installation. Do not broadly swallow widget/programming errors.

### Display-independent snapshot model

Add `longform_core/reader_model.py`, importing no Tk, CLI `Project`, or provider.
Its `load_snapshot(root)` returns a data-only `LoadResult` containing a sanitized
snapshot (or none for invalid required configuration) and source warnings.
It never calls `die`, writes files, reads credential environment variables, or
returns raw JSON/configuration, raw exceptions, or absolute paths. Parsing
helpers are pure transformations; filesystem access is confined to this module's
small read boundary. Optional caching inputs/manifest are separate from displayed
data so tests can load directly without a UI or persistent cache.

Use typed data containers for project identity/totals, ordered scene rows,
per-scene active manuscript, nodes keyed by saved ID, and notes sections.
Read each source once per changed-file load. Accept only validated scalar fields;
never stringify unknown nested dictionaries into visible text. A snapshot has:

- Project: title and target words only, with existing defaults for absent fields
  (`Untitled`, 17000). `project.json` must be a readable JSON object; wrong field
  types are treated as invalid configuration, never echoed.
- Scene cards: ID, chapter, title, status, target words; retain file order. Group
  current scenes by chapter where present, otherwise under Current scenes.
  Reject unsafe/duplicate IDs with a warning (keep the first valid duplicate).
  Discover direct safe tree stems absent from cards in a Retained trees group,
  sorted by ID. Scene IDs/stems allow ASCII letters, digits, underscore, hyphen
  only. Do not use titles or node IDs as filesystem paths.
- Trees: enumerate **all** saved nodes in persisted insertion order, regardless
  of reachability from head. Display ID, parent/children, text, derived words,
  source, model, created, steer, ended/trimmed, and history time/by/text. Missing
  optional metadata is unavailable; false remains false. Discard unknown fields.
  Structural node fields must have valid shapes; warn/skip invalid records.
- Active chain: check head/parent references and cycles before any chain
  traversal. Bind validated in-memory data to a `Tree` allocated without its
  filesystem constructor (`Tree.__new__(Tree)` plus `d`) and call `Tree.text()`;
  count with `words()`. Do not reimplement separators or call `save()`.
  Invalid links make active text unavailable with a warning; independently
  valid node records remain readable under an Unlinked/invalid links group.
  No head means empty active text, not an error.
- Notes: `bible.md`, `state.md`, known `summaries.json` fields (scene ID,
  detailed/brief, updated; arc from/to/text/updated), and sorted direct `*.md`
  files in `checks/` and `critiques/`, including backups. Display all supported
  notes project-wide, not just the selected scene. No markdown/HTML processing.

Current project actual words sum current cards' active text only; retained
trees and inactive nodes never inflate that total. An invalid current tree
contributes no known words and labels the total partial, not silently complete.

Missing optional scenes/trees/notes produce labeled empty data. Malformed JSON,
wrong shapes, decode/read errors, and broken structures produce source-specific
generic warnings and unavailable affected data; unrelated sources still load.
Missing/invalid required `project.json` prevents startup. If it fails during a
refresh, the UI retains the whole last valid snapshot, marks it stale, and retries.
No last-good-file cache is needed for optional sources.

Resolve the chosen root once. Before reads, reject symlinks in any component
below that canonical root and verify resolved sources remain within it.
Enumerate only direct allowlisted files; do not recurse or read arbitrary paths.
Do not read presets, call logs, `.env`, lorebooks, outlines, historical state or
bible directories, cached exports, or any new fields by default. This prevents
accidental private-file inclusion, not hostile concurrent filesystem mutation.
Secrets intentionally placed in prose are prose; the loader is an allowlist, not
a content-redaction engine.

### Widgets consume snapshots, not project objects

Add `longform_core/gui.py` with a testable `ReaderApp(root, project_dir)` that
can populate an already-withdrawn root without starting a mainloop. It owns UI
selection/cache/timer state and reads only through `reader_model`.

| Area | Widgets and behavior |
|---|---|
| Root | Title `<project title> — Longform Reader (read-only)`, initial 1200x800, minimum 900x600, resizable panes |
| Toolbar/status | Refresh now, Auto-refresh checkbutton (on), last completed check time, current scene count and actual/target words, warning/stale indicator |
| Left | Scrollable `ttk.Treeview` with chapter/current and retained groups; ID, title, status, active words; selecting groups does not switch scenes |
| Right | `ttk.Notebook`: Manuscript, Branches, Notes |
| Manuscript | Head/word label and scrollable read-only `tk.Text`, full active scene text |
| Branches | Parent/child `ttk.Treeview` index (ID, words, source, created, head/active markers) and separate full node detail Text pane; parent/child navigation changes selected node only |
| Notes | Scrollable read-only Text with clear source headings/empty states |

Use ttk default platform styling and a readable proportional Tk font around
12–14 points for prose, padding/line spacing, and `wrap="word"`. Disabled Text
widgets prevent typing/paste; allow selection and explicit copy bindings without
temporarily enabling user edits. Application updates briefly enable, replace,
and disable content. No save/editor/head-selection/generation controls.
Tree widget item IDs use internal prefixes/maps to avoid collisions between
group IDs, scenes, and arbitrary saved node IDs.

Select the first current scene, else first retained tree; initially select its
head, else its first node. Branches opens meaningful groups so every node is
discoverable; orphans/invalid-link nodes never vanish from the index. Full node
detail shows labeled text/history without preview truncation.
F5 invokes the same refresh method as the toolbar. Ctrl+Q and WM close share
one teardown that cancels pending timers before destroying the root.

### Refresh only changed data and preserve reader state

Use the Tk event loop, no background UI threads. Schedule a single `after`
callback about 2000 ms after the preceding check completes. Refresh now works
even with auto-refresh off. Toggling off cancels the timer; on schedules exactly
one. Closing cancels it; no callbacks touch destroyed widgets.

Maintain an allowlisted manifest of relative filename, `st_mtime_ns`, size, and
file identity where available. Re-enumerate direct trees/checks/critiques each
check to detect additions/deletions; inspect symlink status before cache reuse.
Unchanged entries reuse sanitized parsed data; changed/added files reread,
removed files disappear. F5/Refresh now force rereads to recover from same-size,
same-mtime external edits; automatic polling cannot promise detection of
deliberately preserved timestamps. Compare resulting snapshots/subviews and do
not rebuild panes whose content is equal. Update last-check time even when
content is unchanged; display warnings for failed checks.

Before applying a changed snapshot capture selected scene/node IDs, tab,
expanded groups, Treeview scroll positions, and each Text pane's first visible
text index (plus horizontal view where applicable). Restore by stable IDs after
population/layout; clamp to available content when text shrinks. Normal append
refresh does not jump to the head or newly added node. If a selected node
disappears choose current head then first saved node; if a selected scene
disappears choose first current scene then first retained tree; otherwise show
empty panes. Scroll preservation applies to surviving content; replacement
selections start at the top. A scene switch resets its node to head/first node,
not an unrelated node ID from the previous scene.

### Tests beside each implementation step

- `tests/test_reader_model.py`: temporary synthetic projects and deterministic
  trees, including long inactive siblings/descendants, saved history, continuation
  joins, counts, retained trees, every notes source, optional absence/bad shapes,
  malformed JSON/recovery, cycles/dangling references, read errors, unsafe
  IDs/symlinks, partial totals, and unknown-field/credential non-disclosure.
  Prove model import/load does not import Tk, call `die`, or construct `Api`.
- CLI coverage uses a fake `gui.launch` and a forbidden `Project`; tests parsing,
  pre-Project dispatch, help without Tk, success/failure lifecycle, and concise
  missing Tk/display errors. Model/CLI tests never require a desktop.
- `tests/test_gui.py`: fixture imports Tk and probes a withdrawn root. Only
  ImportError or Tk display/library initialization failure is an availability
  skip, with a reason; failures after that probe are real failures. Create the
  app withdrawn using a temp project, drain idle geometry, assert scene/tab/
  full-text population, select inactive descendants and history, modify fixtures,
  refresh and assert surviving selections, tab, expansion, and top visible text
  index. Check clipboard/read-only behavior, F5/close, empty/error recovery, and
  cleanup. Exercise timer scheduling/toggle/cancel with an injected scheduler or
  controlled callbacks, never two-second sleeps. Probe platform display
  availability rather than assuming an environment variable always suffices.
- Spy on reads and widget replacement to prove unchanged automatic refresh does
  not reload/rebuild; force-refresh tests prove explicit rereads. Hash files and
  compare directory entries before/after the full UI session. Keep existing API/
  socket guards intact; prohibit browser/server launch with fakes where useful.
- Reuse pytest discovery in `scripts/check.sh`, not a separate GUI runner. Run
  normal display-capable checks and a headless variant (unset DISPLAY and
  WAYLAND_DISPLAY on Linux); only real-widget tests skip headless. Add subprocess
  coverage for missing Tk imports and check failure propagation without masking
  test failures as skips. Use the same uv-managed runtime for both modes.

## Risks / Trade-offs

- Tk availability differs by Python distribution → lazy imports, concise
  diagnostics, uv demo; no new dependency or automatic installation.
- Synchronous scanning can pause for very large projects → cache unchanged
  sources and replace only changed panes; accept no worker framework for now.
- File saves across sources are not transactional → snapshot each file once,
  warn on transient errors, retry; never change existing persistence.
- Hidden widget smoke tests cannot assess every visual detail → deterministic
  widget assertions plus the documented native-window demo.
- Auto-refresh uses file metadata → forced refresh handles unusual externally
  preserved timestamps; no speculative filesystem watcher.

## Migration Plan

No data migration. Add the command/modules behind test-first commits, update
AGENTS run/layout facts when implemented, and run the proposal's native demo
against synthetic data while saving another branch. Rollback removes the
additive reader command/modules; existing writing files and CLI remain intact.
No unresolved product or architectural questions remain.
