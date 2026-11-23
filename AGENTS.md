# writing

## What this is
CLI for writers planning and collaboratively drafting long-form fiction with Featherless.ai: a thin `longform.py` launcher over the `longform_core/` package (ADR-0003).

## Stack
Python 3.11+, uv script runner, PEP 723 inline `httpx>=0.27`; argparse CLI, JSON/Markdown files, no database.

## Checks
`./scripts/check.sh`: py_compile; CLI `--help` if uv exists; `== standalone` (builds `dist/longform` through `scripts/build-standalone.sh` and runs the frozen executable tests — needs uv and a C compiler providing `cc` for the test-only network guard, never skipped); source pytest for the remaining regression suite (fails without uv).
Suite: `uv run --with pytest --with httpx pytest -q tests` (includes `tests/test_standalone.py`, which builds the standalone executable through the production script when `dist/longform` is missing or stale and runs it away from the checkout; `./scripts/check.sh` builds it once and the frozen tests reuse that artifact); no lint step.
`ock check` runs committed checks in a clean checkout; there is no hosted CI workflow (`ock ship` runs checks locally before opening the PR).
Run / demo: `uv run --script longform.py --help` prints commands without API calls.
Current main has no `gui` command. The separate `feat/reader-gui` branch contains
a read-only Tkinter/ttk GUI and `reader_model` snapshots; do not assume that
branch is already integrated.

## Planned desktop workspace
`docs/ROADMAP.md` extends the completed CLI foundation with three GUI milestones:
Wayland steer/generate/accept, setup/planning and draft controls, then continuity/
review/revision/export. These are plans, not implemented commands or OpenSpec changes.
ADR-0006 selects PySide6/Qt Widgets for the expanded native Wayland workspace;
ADR-0007 selects incremental shared operations and one background GUI worker.
Reuse existing commands/core behavior and the pending reader's safe snapshots,
not terminal automation or a second writing engine. Keep CLI prompts/files
compatible. Verify the actual uv/Qt/Wayland runtime before claiming support.
The implementation must add offline operation/button-flow tests to
`scripts/check.sh`; model tests stay headless, Qt widget tests use offscreen
execution, and real Wayland desktop acceptance is separate. Do not weaken the
existing network guard or claim headless tests establish compositor support.

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
