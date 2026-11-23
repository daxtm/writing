# writing

## What this is
CLI for writers planning and collaboratively drafting long-form fiction with Featherless.ai: a thin `longform.py` launcher over the `longform_core/` package (ADR-0003).

## Stack
Python 3.11+, uv script runner, PEP 723 inline `httpx>=0.27` and `pyside6>=6.12.0,<6.13`; argparse CLI, JSON/Markdown files, no database.

## Checks
`./scripts/check.sh`: py_compile; CLI `--help` if uv exists; pytest if `tests/` exists (fails without uv).
Suite: `uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' pytest -q tests`; no lint/build step.
The launcher declares `pyside6>=6.12.0,<6.13` beside `httpx`: `uv run --script longform.py …` downloads
PySide6 (~hundreds of MB of wheel downloads plus installed size, and the matching `uv` cache) on first
use even for CLI-only users, as accepted in ADR-0006; GUI imports stay lazy, so `--help` needs no display.
`ock check` runs committed checks in a clean checkout; there is no hosted CI workflow (`ock ship` runs checks locally before opening the PR).
Run / demo: `uv run --script longform.py --help` prints commands without API calls.
GUI demo: `QT_QPA_PLATFORM=wayland uv run --script longform.py gui DIR` opens one native Wayland window
(reading all saved branches/notes, per-scene steering Save/Clear; no generation yet). `gui` refuses any
explicit platform except `wayland`, never falls back to XWayland, and prints recovery guidance when
Wayland is unavailable. Model/CLI tests run headless; Qt widget tests run offscreen in a subprocess
(`tests/qt_widget_cases.py`, never skipped); real Wayland acceptance is a separate desktop step and was
recorded for `gui-wayland-shell` (KWin 6.8.3, PySide6 6.12.0, DPR 1.0; interactive scaling/theme checks
still pending with the owner).

## Planned desktop workspace
`docs/ROADMAP.md` extends the completed CLI foundation with three GUI milestones:
Wayland steer/generate/accept, setup/planning and draft controls, then continuity/
review/revision/export. M1's first change, `openspec/changes/gui-wayland-shell/`,
is implemented on `feat/gui-wayland-shell`: the `gui` command opens the Qt
Widgets reading/steering shell over `longform_core.reader_model` snapshots with
per-scene steering via `longform_core.scene_steering`; generation, acceptance,
and the background worker remain for `gui-steered-drafting` (do not create it yet).
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
- `longform_core/`: the implementation — `config` (constants, default config, templates), `utils` (logging, file/JSON/text, diff/parse helpers), `project`, `api`, `tree`, `lore` (cards/books/matching), `prompt`, `checks`, `commands` (cmd_* and interactive helpers), `cli` (argparse/main); `reader_model` (UI-independent sanitized snapshots), `scene_steering` (Qt-independent per-scene steering write adapter), `gui` (Qt-free Wayland startup policy/dispatch), `gui_window` (PySide6 Qt Widgets shell).
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
