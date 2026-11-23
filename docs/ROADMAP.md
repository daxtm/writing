# Roadmap

## Goal

Make `longform.py` safe to change through observable offline regression tests,
then extract only the boundaries the prototype actually needs. Preserve
`uv run --script longform.py …` and existing project files and reports.

Extend that foundation into a polished Linux desktop writing workspace:
run the existing planning, drafting, review, and export flow through buttons,
with a persistent multiline steering box and native Wayland support. The CLI
remains available and uses the same writing operations and project files.

## Out of scope

New model/provider capabilities, autonomous whole-book generation, browser/server
interfaces, cloud accounts, collaborative concurrent editing, rich-text/DOCX
editing, standalone installers, private sample/preset fixtures, and live API
tests. Existing CLI capabilities becoming GUI controls are in scope; changing
their prompts, sampling policy, or file formats is not. Dependency provisioning
may use network; test execution must not.

## Planning baseline

This extends the completed foundation below; the GUI milestones remain
unimplemented plans. Only M1's first change has been selected for proposal:
`openspec/changes/gui-wayland-shell/`; subsequent items have no change artifacts.
`origin/main` currently has the CLI but no `gui` command. The separate
`feat/reader-gui` branch contains the Tkinter/ttk reader, UI-independent
`reader_model` snapshots, and ADR-0004/0005; it is not yet on main.
Reuse its safe reading/model behavior and tests when available, not a second
reader or a second writing engine. Integrating that work is a prerequisite of
GUI milestone 1, not an instruction to merge it here.

The existing `cmd_*` commands already implement the flow, but their `ask`,
`$EDITOR`, paging, printing, and blocking API calls prevent direct button
invocation. Extract only the operation being exposed, keep the CLI as an adapter,
and reuse `Project`, `Tree`, `Lore`, prompt/check helpers, and `Api`.
New desktop controls are necessary because neither the CLI nor the separate
read-only reader supplies editable, asynchronous workflow interactions.

## GUI milestone 1 — Walking skeleton: steer, generate, accept on Wayland

- [x] gui-wayland-shell — Replace the pending Tk presentation with a native Wayland Qt Widgets reading shell: safe snapshots, all-branch/notes navigation, state-preserving refresh, and persistent steering Save/Clear; no generation/acceptance/worker yet.

Implemented on `feat/gui-wayland-shell`: `gui DIR` opens the PySide6 shell over
`reader_model` snapshots with steering persisted by `scene_steering`; PySide6
6.12.0 in the launcher/check environment; headless model/CLI tests plus
offscreen widget cases in `scripts/check.sh`. Real Wayland acceptance recorded
in the change's design.md (KWin 6.8.3/Plasma 6.8.3, platform `wayland`,
1920×1080 DPR 1.0, one window, steering persisted, clean close exit 0);
interactive scaling, theme switching, and mouse/keyboard work remain owner
acceptance. M1 stays open: `gui-steered-drafting` (generation, preview,
acceptance, Stop, background worker) is still unchecked.
- [ ] gui-steered-drafting — Extract shared draft operations and connect scene selection, saved steering, one-candidate generation, preview, acceptance, and cooperative stop to a responsive background worker.

Depend on the reader baseline above; `gui-steered-drafting` depends on
`gui-wayland-shell`. Start with an existing synthetic project containing a
preset and one planned scene. The shell must have a resizable scene/branch
sidebar, readable manuscript/candidate area, multiline steering box, a clear
primary action, and a status/error area. Use consistent spacing and typography,
system light/dark palette with readable contrast, keyboard focus, and adjustable
prose size; do not postpone all visual work to a later polish phase.

Steering is the existing per-scene `Tree.d["steer"]`: Save steering persists it,
Clear saves an empty value, and Generate captures/saves the current box before
building the existing writer prompt. It remains active until changed, survives
reopening, and is recorded on each candidate exactly as in the CLI. Selection
changes with unsaved text offer Save/Discard/Cancel. Generated candidates are
saved branches, not accepted prose; only Accept moves the active head.

One project operation runs at a time. Reading remains usable while generating;
conflicting writes/project switches are disabled. Stop enters a visible
stopping state and cancels cooperatively at an I/O boundary, not by killing a
thread; network waits remain bounded by configured request timeouts. Keep
already saved branches and accepted text; never save a partial streamed passage.
Closing during work offers Stop and wait or Keep open, and closes only after
the worker settles. Refresh must not overwrite dirty editors. Compare captured
inputs before writes; external changes require reload/retry rather than a stale
overwrite. Concurrent CLI/GUI writers are unsupported.

Observe after implementation:
`QT_QPA_PLATFORM=wayland uv run --script longform.py gui /path/to/project`.
Without relying on XWayland, select the scene, type direction, Generate, scroll
while text arrives, and Accept. Close/reopen: the accepted passage and steering
remain; CLI status/export sees the same text. Inject a fake API failure: readable
error, no active-head change, controls usable again.

Accept this milestone only with offline fake-provider button-flow tests and a
real Wayland smoke recording the compositor, Qt platform name (`wayland`),
runtime version, and 100%/200% plus available fractional/mixed-monitor scaling,
clipboard, focus, resize, and file-dialog results. Offscreen widget tests do not
prove compositor integration. Missing Qt/Wayland support must produce an
actionable diagnostic, not silently fall back in this explicit launch mode.

Decisions forced now:
[ADR-0006](adr/0006-wayland-writing-workspace.md) chooses the presentation toolkit
and supersedes the reader's Tk/no-new-dependency restriction for this workspace;
[ADR-0007](adr/0007-shared-writing-operations.md) fixes the shared-operation and
background-execution boundary.

## GUI milestone 2 — Set up, plan, and control drafting without a terminal

- [ ] gui-project-planning — Add Create/Open, preset import, model/role settings, limits, bible question forms, outline notes/candidate choice, and scene generation/editing with overwrite confirmation.
- [ ] gui-draft-controls — Add multi-candidate generation/reroll, manual passage entry/edit/history, rewind/jump/delete eligible branches, passage length, POV/cast, lorebook toggles/classification/aliases, prompt-budget inspection, and scene completion.

Both depend on milestone 1; planning precedes the from-empty-project demo.
Use existing initialization, bible forms/history, outline selection, scene
validation, and draft semantics. A settings form edits only explicitly supported
nonsecret configuration fields; obtain credentials through the existing
environment-variable mechanism, display its variable name/missing-key status,
and never display/log an existing key. Import presets/lore files through desktop
file pickers with existing validation. Edit supported planning text in built-in
plain-text panes with Save/Cancel, never launch `$EDITOR` or ask in a terminal.
Outline regeneration/selection and scene replacement preserve existing
confirmation and history behavior. Disabled controls explain missing
prerequisites; no implicit paid call or automatic next command.

Observe: launch `uv run --script longform.py gui /path/to/new-project` and use
Create when the directory is absent. With credentials already in the environment,
choose models/preset, fetch limits, fill the bible, choose an outline, create a
scene, generate two candidates, reroll one, edit/accept one, explore the retained
branch, and mark the scene done—all without terminal prompts or external editors.
The offline test performs that same sequence with temporary files and fake
responses, and compares CLI/GUI prompt and saved-tree behavior.

## GUI milestone 3 — Finish continuity, review, revision, and export

- [ ] gui-continuity-review — Add summary/state preview, edit/regenerate/accept, summary-only mode and earlier-scene warning, plus arc compression range/replace and preview/accept.
- [ ] gui-check-revise-export — Add critique and deterministic checks, editable review notes, passage revision diffs with accept/skip/edit/regenerate/quit, project status, and manuscript export with destination selection.

Both depend on milestone 2; they reuse the execution boundary already chosen,
not a new job system. Preserve `state_history`, summaries, revision history,
stale-summary warnings, arc overlap checks, and existing report/export formats.
Status and notes remain visible alongside the writing pane; each save refreshes
affected views without losing the current reading position. Destructive or
replacement actions name their target and require the existing confirmation.

Observe: from a completed scene, update continuity after reviewing its diff,
compress a valid scene range, run critique/check, accept one revision and skip
another, refresh stale summaries, then Export. The saved manuscript matches the
CLI export for the same active paths; restart restores the saved project state.
Offline end-to-end tests cover this full flow, including rejection/error paths,
without credentials, `$EDITOR`, terminal input, or network access.

## Delivery rules for every GUI change

Create its OpenSpec proposal only when that change is selected for build. Keep
each change to at most eight test-first tasks: the first proves the visible
behavior and initially fails; the last makes `scripts/check.sh` run the new
coverage. Preserve existing offline network guards and CLI parity tests. Model
and operation tests always run headless; Qt widget tests use the offscreen
platform in a subprocess with the GUI runtime installed and must not silently
skip missing dependencies. Real Wayland checks are a separate required desktop
acceptance step; document unavailable compositor coverage rather than claiming
headless success proves it. No separate hardening/polish milestone is planned.

## Open questions

- Which compositor/distribution and monitor scaling form the owner's primary
  acceptance setup? Native Wayland is the target, not merely an XWayland window.
- Runtime feasibility is verified: uv resolved PySide6 6.12.0 and a minimal
  explicit Wayland app reported `wayland`, 1920x1080, DPR 1.0, without XWayland.
  `gui-wayland-shell` proposes `pyside6>=6.12.0,<6.13` in the launcher/check
  environment; actual workspace/compositor/scaling acceptance remains separate.
- Any visual reference or preferred reading font? Until supplied, use the
  system palette, restrained controls, and adjustable prose typography above.

## Phase 0 — Walking skeleton: source, checks, and project facts

- [x] testing-foundation — Track the CLI, replace scaffold checks with real syntax/help/test discovery, and record project facts and this plan on `chore/testing-foundation`.

Source, checks, and documentation landed in `09bb632`, `2609c34`, and PR #1. At
the time, `./scripts/check.sh` showed `== syntax`, `== cli smoke` when uv exists,
and an explicit `no tests/ yet` message until Phase 1. Without uv, syntax still
runs and help is explicitly skipped.
`uv run --script longform.py --help` prints the available commands without an API key.

## Phase 1 — Offline regression suite

- [x] add-test-suite — Run deterministic pytest coverage of helpers, branch trees, reports, and mocked API behavior.

Cover `clean_continuation`; `key_match`, `entry_triggered`, `name_variants`;
`split_bible`, `join_bible`; `extract_json_array`, `extract_tagged`;
`writer_sampling`, `render_story_string`; and `Tree` operations including
save/reload. Extract a pure banned-phrase/n-gram report helper from `cmd_check`
only as needed, preserving its output. Test `Api` via `httpx.MockTransport`,
using synthetic streams, fake projects/clocks/sleep, and no real credentials.
`tests/conftest.py` puts the repository root on `sys.path`; no packaging yet.

Observe with `uv run --with pytest --with httpx pytest -q tests`: tests are
collected and report `N passed`, exit 0. `./scripts/check.sh` adds `== tests` and
the same passing summary. Test failures must fail the script. Checks run
locally; no CI workflow is involved.

## Phase 2 — Extract pure core pieces behind tests

- [x] extract-pure-core — Separate remaining calculation from I/O in place, prioritizing deterministic checks, card/lore parsing, and prompt assembly.

Reuse existing pure helpers and the Phase 1 checker; do not extract them twice.
Keep the script and CLI shape unchanged. Add focused tests before each necessary
extraction; move filesystem/network orchestration outside those helpers.
Observe with `uv run --with pytest --with httpx pytest -q tests` and
`./scripts/check.sh`: both stay green, with identical fixed-fixture reports and
prompt strings before and after extraction.

Extracted boundaries (each behind a test-first commit): `card_png_json(data)`
plus a thin `read_card_png` wrapper (`tests/test_card.py`), `parse_book_data(d,
stem)` plus a thin `parse_book` wrapper (`tests/test_book.py`),
`layered_summary_core(sums, cfg, …, est, root)` plus a thin `layered_summary`
wrapper (`tests/test_summary.py`), and `compose_writer_prompt` /
`tail_trim_chars` split out of `build_writer_prompt` (`tests/test_writer_prompt.py`
with a stored `tests/data/writer_prompt_fixture.json` parity fixture covering
scene start, continuation, and steer).

## Phase 3 — Package split

- [x] split-cli-package — Move the tested implementation into a package while retaining the thin uv launcher.

The owner asked to split now despite the gate check below coming back "not
triggered"; ADR-0003 supersedes ADR-0002 to record that deliberate override.
`longform.py` stays at the repo root as a thin PEP 723 launcher re-exporting
the public names; the implementation moved to `longform_core/` (`config`,
`utils`, `project`, `api`, `tree`, `lore`, `prompt`, `checks`, `commands`,
`cli`) as a move-only refactor.

Result: `uv run --script longform.py --help`, the full offline suite, and
`./scripts/check.sh` all stay green with byte-identical CLI help and
fixed-fixture reports/prompts; 154 tests pass. One-file portability is
sacrificed even though the launcher command stays the same.

## Decisions

- [ADR-0001: Record architecture decisions](adr/0001-record-architecture-decisions.md).
- [ADR-0002: Keep the single-file CLI through the prototype](adr/0002-single-file-cli.md)
  accepted the prototype trade-off and defined extraction/package triggers;
  superseded by ADR-0003.
- [ADR-0003: Split the CLI into a package now](adr/0003-split-into-package.md)
  records the owner's deliberate override of the ADR-0002 gate and the package
  layout.
- [ADR-0006: Use Qt Widgets for the Wayland writing workspace](adr/0006-wayland-writing-workspace.md).
- [ADR-0007: Share writing operations between CLI and an asynchronous GUI](adr/0007-shared-writing-operations.md).

ADR-0004/0005 are already allocated on `feat/reader-gui`; keep those numbers
and records when integrating it rather than reusing them on this roadmap branch.
