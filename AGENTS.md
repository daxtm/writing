# writing

## What this is
CLI for writers planning and collaboratively drafting long-form fiction with Featherless.ai: a thin `longform.py` launcher over the `longform_core/` package (ADR-0003).

## Stack
Python 3.11+, uv script runner, PEP 723 inline `httpx>=0.27`; argparse CLI, JSON/Markdown files, no database.

## Checks
`./scripts/check.sh`: py_compile; CLI `--help` if uv exists; pytest if `tests/` exists (fails without uv).
Suite: `uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' pytest -q tests`; no lint/build step.
The launcher declares `pyside6>=6.12.0,<6.13` beside `httpx`: `uv run --script longform.py …` downloads
PySide6 (~hundreds of MB of wheel downloads plus installed size, and the matching `uv` cache) on first
use even for CLI-only users, as accepted in ADR-0006; GUI imports stay lazy, so `--help` needs no display.
`ock check` runs committed checks in a clean checkout; there is no hosted CI workflow (`ock ship` runs checks locally before opening the PR).
Run / demo: `uv run --script longform.py --help` prints commands without API calls.
Current main has no `gui` command. The separate `feat/reader-gui` branch contains
a read-only Tkinter/ttk GUI and `reader_model` snapshots; do not assume that
branch is already integrated.

## Planned desktop workspace
`docs/ROADMAP.md` extends the completed CLI foundation with three GUI milestones:
Wayland steer/generate/accept, setup/planning and draft controls, then continuity/
review/revision/export. These are plans, not implemented commands.
`openspec/changes/gui-wayland-shell/` is the selected M1 first-change proposal:
Qt shell/reading and persistent steering only. Generation, acceptance, and the
background worker remain for `gui-steered-drafting`; do not create it yet.
ADR-0006 selects PySide6/Qt Widgets for the expanded native Wayland workspace;
ADR-0007 selects incremental shared operations and one background GUI worker.
Reuse existing commands/core behavior and the pending reader's safe snapshots,
not terminal automation or a second writing engine. Keep CLI prompts/files
compatible. The owner verified a minimal uv PySide6 6.12.0 app with explicit
`QT_QPA_PLATFORM=wayland` reporting `wayland`, 1920x1080, DPR 1.0, not XWayland.
This is runtime feasibility, not acceptance of the planned workspace.
The shell plans `pyside6>=6.12.0,<6.13` in the launcher and existing check
environment: increased clean-checkout downloads/disk use includes CLI-only uv
users. GUI imports stay lazy, so `--help` still needs no display.
The implementation must add offline operation/button-flow tests to
`scripts/check.sh`; model tests stay headless, Qt widget tests use offscreen
execution, and real Wayland desktop acceptance is separate. Do not weaken the
existing network guard or claim headless tests establish compositor support.
After implementation, demo with
`QT_QPA_PLATFORM=wayland uv run --script longform.py gui DIR`.
Until then the Checks and Layout sections above/below describe current code;
the build must update them when Qt modules and coverage actually land.

## Layout
- `longform.py`: thin PEP 723 launcher; re-exports the package's public names so `import longform` keeps working.
- `longform_core/`: the implementation — `config` (constants, default config, templates), `utils` (logging, file/JSON/text, diff/parse helpers), `project`, `api`, `tree`, `lore` (cards/books/matching), `prompt`, `checks`, `commands` (cmd_* and interactive helpers), `cli` (argparse/main).
- `scripts/`: check entry point; `tests/`: offline pytest suite.
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
