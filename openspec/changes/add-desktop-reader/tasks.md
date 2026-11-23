# Tasks

## 1. Native read-only desktop reader

Each checkbox is one small commit with its tests beside the behavior. Use
synthetic temporary projects only; keep the launcher and persisted formats
unchanged. The first commit intentionally records a failing acceptance contract;
do not xfail it or weaken assertions to make the unimplemented command pass.

- [x] 1.1 Add the failing writer-visible acceptance tests: `gui DIR` invokes a fake desktop launcher before any shared `Project` construction, and a Tk/display-guarded withdrawn-app test lists a scene and displays its full active/inactive text; run them and record failure against the current CLI rather than skipping missing application code.
- [x] 1.2 Add `reader_model` scene/tree snapshots and safe in-memory reuse of `Tree.text()`/`words()`; add offline tests for card order, chapter/retained groups, active-only totals, all saved branches/descendants, metadata/history, no head, and exact continuation joins; all model tests run without Tk, credentials, or provider calls.
- [x] 1.3 Complete allowlisted notes and recoverable loading in the model; add tests for all notes/backups, missing files, malformed JSON/shapes, cycles/dangling links, partial totals, read failures/recovery, unsafe IDs/symlinks, and synthetic secret/unknown-field exclusion from results and diagnostics.
- [x] 1.4 Build `ReaderApp`'s native ttk scene list, Notebook, Manuscript pane, title, status/totals, typography and minimum size; add guarded withdrawn-widget tests for selection, empty/retained scenes, full text/count population, wrapping/scrollbars, and headless-safe availability probing that never skips application failures.
- [x] 1.5 Complete Branches index/detail/navigation/history and project-wide Notes with disabled, selectable/copyable Text panes; add withdrawn-widget tests for inactive descendants, full long text/history, false/missing flags, plain-text notes, no edits on typing/paste, no head mutation, and unchanged project hashes/directory entries.
- [x] 1.6 Add metadata-cached auto-refresh, force-refresh/F5, toggle, last-check time, stale/error recovery, and close-time timer cancellation; test changed/unchanged reads, preserved scene/node/tab/expansion/top-visible position, removed-selection fallback, and single-timer scheduling without sleeps or browser/server/network exceptions.
- [x] 1.7 Wire lazy `gui DIR` argparse dispatch and blocking launcher lifecycle, Ctrl+Q/window close, and concise missing Tk/display/invalid-project errors; pass the first acceptance contract plus fake-launcher/error/help-without-Tk tests, and update AGENTS run/layout facts with the read-only uv demo.
- [x] 1.8 Make `scripts/check.sh` cover the new model/CLI/guarded widget tests through its existing pytest discovery (adjust only existing check comments/wiring if needed, no second runner); verify failure propagation and run `./scripts/check.sh` with a display and `env -u DISPLAY -u WAYLAND_DISPLAY ./scripts/check.sh` on Linux, with only unavailable real-widget tests skipped and the full existing suite passing.
