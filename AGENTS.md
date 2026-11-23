# writing

## What this is
CLI for writers planning and collaboratively drafting long-form fiction with Featherless.ai: a thin `longform.py` launcher over the `longform_core/` package (ADR-0003).

## Stack
Python 3.11+, uv script runner, PEP 723 inline `httpx>=0.27` and `pyside6>=6.12.0,<6.13`; argparse CLI, JSON/Markdown files, no database.

## Checks
`./scripts/check.sh`: py_compile; CLI `--help` if uv exists; `== standalone`
(builds `dist/longform` through `scripts/build-standalone.sh` and runs the frozen
executable tests — needs uv and a C compiler providing `cc` for the test-only
network guard, never skipped); source pytest for the remaining regression and
GUI/Qt cases (fails without uv).
Suite: `uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' pytest -q tests`;
includes `tests/test_standalone.py`, which builds the standalone executable through
the production script when `dist/longform` is missing or stale and runs it away
from the checkout; `./scripts/check.sh` builds it once and the frozen tests reuse
that artifact; no lint step.
The launcher declares `pyside6>=6.12.0,<6.13` beside `httpx`: `uv run --script longform.py …` downloads
PySide6 (~hundreds of MB of wheel downloads plus installed size, and the matching `uv` cache) on first
use even for CLI-only users, as accepted in ADR-0006; GUI imports stay lazy, so `--help` needs no display.
`ock check` runs committed checks in a clean checkout; there is no hosted CI workflow (`ock ship` runs checks locally before opening the PR).
Run / demo: `uv run --script longform.py --help` prints commands without API calls.
GUI demo: `QT_QPA_PLATFORM=wayland uv run --script longform.py gui DIR` opens one native Wayland window
(the complete draft loop: reading all saved branches/notes, per-scene steering Save/Clear, Generate with
count/swipes and streaming preview, candidate tray Accept/Reroll selected/all/Add N/View/Delete leaf/
Keep branches/Discard, built-in New passage/Edit head editors with diff/history, Rewind/Use as head/
Delete leaf/marked manuscript/Tail N, Scene tab card/POV/cast/session length/Mark done/Next unfinished,
Context tab budget/samplers/injected-lore/exact prompt/Save last_prompt.txt, Lore tab toggles/classify/
aliases/import). Generation runs through `longform_core.draft_operations` (Qt-independent, ADR-0007) on
one background worker (`longform_core.draft_worker`); the CLI `draft` loop is an adapter over the same
operations with frozen prompts/transcripts (`tests/test_draft_parity.py`). Stop is cooperative at
request/chunk/save boundaries, close offers Stop-and-wait/Keep open, stale sources refuse writes.
`gui` refuses any explicit platform except `wayland`, never falls back to XWayland, and prints recovery
guidance when Wayland is unavailable. Model/CLI tests run headless; Qt widget tests run offscreen in a
subprocess (`tests/qt_widget_cases.py`, never skipped; 38 cases, all enforced
by an unregistered-case guard). Real Wayland acceptance for the
drafting loop (generation/Stop/close, picker, keyboard, scaling/theme) is recorded as PENDING in
`openspec/changes/gui-drafting-workspace/evidence.md` and remains a separate owner desktop step; the
shell's pre-drafting smoke (KWin 6.8.3, PySide6 6.12.0, DPR 1.0) predates generation.

## Planned desktop workspace
`docs/ROADMAP.md` requires every CLI/TUI feature in the GUI, start to finish;
no individual change completes the workspace. The sequence is
`gui-drafting-workspace` (implemented), `gui-project-planning` (implemented),
then `gui-continuity-review-export` (implemented). M1's first change, `openspec/changes/gui-wayland-shell/`,
is implemented on `feat/gui-wayland-shell`: the `gui` command opens the Qt
Widgets reading/steering shell over `longform_core.reader_model` snapshots with
per-scene steering via `longform_core.scene_steering`; the implemented shell is
unshipped. `openspec/changes/gui-drafting-workspace/` is now implemented on
`feat/gui-wayland-shell`: the complete draft loop through shared operations
(`longform_core.draft_operations`), one worker (`longform_core.draft_worker`),
cooperative Stop, stale-write refusal, and CLI adapters with byte-identical
transcripts; real Wayland acceptance for drafting remains pending
(`evidence.md`). `openspec/changes/gui-project-planning/` is now implemented on
`feat/gui-wayland-shell`: Create/Open with create-missing-only init and
validated preset import, the supported nonsecret settings form with explicit
Fetch limits (credential name/availability only), bible forms/section
acceptance/direct edits/history, outline notes/competing
candidates/choose/edit, scene generation/previews/confirmed replacement and
saved-card editing — all through shared Qt-independent
`longform_core.planning_operations` on the one worker; the offscreen
Create-to-scene journey (`case_planning_journey`) is green and CLI/GUI
parity is frozen in `tests/test_planning_ops.py`; real Wayland
Create-to-scene acceptance is recorded as PENDING in the change's
`evidence.md`. Planning is unshipped. Continuity/review/export
(`openspec/changes/gui-continuity-review-export/`) is implemented on
`feat/gui-wayland-shell` (all eight tasks), unshipped. It covers
update-state/summary-only, compression, critique/check reports and
editing, passage revision, read-only full status and destination-picked export
through ADR-0007 shared operations/the existing worker, with one-worker
settlement and dirty-source Save/Discard/Cancel before Revise/Export; the
offscreen review journey (`case_review_journey`) and CLI/GUI parity
(`tests/test_review_ops.py`) are green, and the M1–M3 parity audit is
recorded in its `evidence.md`. Real Wayland M3
acceptance is PENDING, not inferred from offscreen tests. Stop planning after
this proposal; the roadmap parity matrix across M1–M3 has been audited row by
row (controls/tests/evidence, explicit gaps in the change's `evidence.md`),
but the full workspace is still not claimed complete. Do not ship.
Full completion requires setup through export, all draft actions, offline
CLI/GUI parity and separate real Wayland acceptance; this plan does not authorize shipping.
ADR-0004/0005 (integrated from the reader baseline; 0005 superseded by ADR-0006)
select PySide6/Qt Widgets for the expanded native Wayland workspace;
ADR-0007 selects incremental shared operations and one background GUI worker.
Keep existing commands/core behavior and the reader's safe snapshots; keep CLI
prompts/files compatible. The shell's real Wayland acceptance was recorded in
the change's design.md (KWin 6.8.3, `wayland`, PySide6 6.12.0, 1920×1080, DPR
1.0, one window, steering persisted, close exit 0); interactive scaling, theme
switching, and mouse/keyboard work remain an owner acceptance step.

## Layout
- `longform.py`: thin PEP 723 launcher; re-exports the package's public names so `import longform` keeps working.
- `longform_core/`: the implementation — `config` (constants, default config, templates), `utils` (logging, file/JSON/text, diff/parse helpers), `project`, `api`, `tree`, `lore` (cards/books/matching), `prompt`, `checks`, `commands` (cmd_* and interactive helpers), `cli` (argparse/main); `reader_model` (UI-independent sanitized snapshots), `scene_steering` (Qt-independent per-scene steering write adapter), `planning_operations` (Qt-independent init/settings/limits/bible/outline/scenes operations), `gui` (Qt-free Wayland startup policy/dispatch), `gui_window` (PySide6 Qt Widgets shell).
- `scripts/`: check entry point; `tests/`: offline pytest suite (headless model/CLI tests plus `tests/qt_widget_cases.py`, the offscreen Qt widget subprocess cases launched by `tests/test_qt_cases.py`).
- `openspec/`: behavior specs and changes; `docs/`: roadmap and ADRs.
- `.github/`: PR template; `myfic/`: private generated sample, never a test fixture.

## Rules
- Specs: `openspec/`. Decisions: `docs/adr/`. Plan: `docs/ROADMAP.md`.
- Roadmap changes get OpenSpec artifacts only when selected for implementation;
  no speculative change directories. ADR-0004/0005 are reserved on `feat/reader-gui`.
- Keep `myfic/` and the third-party `56295265-LLam_ception-1.3.json` preset untracked.
- Never commit API keys or `.env`; synthetic test credentials only.
- Tests are offline/deterministic: no live API calls; use MockTransport/fakes and temporary projects.
- Keep `longform.py` as the thin PEP 723 launcher over `longform_core/` (ADR-0003); behavior, output, and file formats are frozen behind the test suite. Monkeypatch at the owning module (e.g. `longform.api.warn`), not the launcher re-exports.
