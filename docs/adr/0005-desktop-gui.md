# ADR-0005: Use Tkinter and ttk for the native read-only desktop reader

- Status: Superseded by ADR-0006
- Date: 2026-11-23
- Related: add-desktop-reader; supersedes ADR-0004; docs/ROADMAP.md

## Context
The owner rejected the unimplemented browser/HTML proposal and requires a real
desktop GUI alongside terminal drafting. The reader must expose every saved
branch and supporting notes, remain read-only, and add no dependencies. Existing
tree files and CLI behavior must remain unchanged behind ADR-0003's launcher.
The owner verified Tk 9.0.4 in the uv-managed Python 3.13 runtime and an available
display (`DISPLAY=:0`, 6400x1080); the system Python lacks Tk libraries.

## Options
1. Tkinter with ttk widgets in the CLI's uv runtime — standard-library native
   desktop window without a server or new dependencies, but requires an
   available Tk installation/display and maintaining desktop widget state.
2. Keep ADR-0004's standard-library local web reader — no new Python
   dependencies and accessible through a browser, but still an HTML page rather
   than the native GUI the owner explicitly requires.
3. A Qt-based native reader — mature desktop widgets and styling, but adds a
   substantial external dependency and packaging surface.

## Decision
Choose option 1. The deciding reason is that Tkinter plus ttk provides the
requested native desktop interface within the zero-new-dependencies constraint;
the required uv runtime has already been verified locally.

Add `gui DIR`, lazily loading the desktop entry point before shared `Project`
construction. Keep safe, allowlisted project snapshots in a UI-independent
module; Tk widgets consume only those snapshots. Use ttk Treeviews and a
Notebook with read-only Text panes, and refresh saved files through the Tk
event loop. Do not add a browser, HTML renderer, HTTP listener, API/provider
calls, editing controls, or configuration viewer.

ADR-0004 remains historical with only its status changed. Delete the rejected,
unimplemented `add-reader-gui` change rather than archiving it as shipped; git
history retains the rejected proposal. No web capability was implemented.

## Consequences
- Good: a real desktop reading window shows saved inactive branches without
  replacing terminal drafting or changing persisted formats.
- Good: no new dependencies, server lifecycle, browser integration, or network
  exception in the offline test guard.
- Good: data loading and privacy/error tests run without importing Tk or using a
  display; display-capable runs also exercise actual withdrawn widgets.
- Bad: Tk is not present in every Python distribution; use `uv run --script
  longform.py gui DIR`, not the system Python, and report missing Tk/display
  concisely. Automatic installation of Tk is not included.
- Bad: typography, selection/scroll restoration, timers, and platform differences
  are maintained here; headless skips alone cannot prove visual behavior.
- Bad: synchronous file refresh can pause on very large projects and shows saved
  files, not unsaved streamed tokens; separate files are not a transaction.
