# writing

## What this is
Single-file CLI for writers planning and collaboratively drafting long-form fiction with Featherless.ai.

## Stack
Python 3.11+, uv script runner, PEP 723 inline `httpx>=0.27`; argparse CLI, JSON/Markdown files, no database.

## Checks
`./scripts/check.sh`: py_compile; CLI `--help` if uv exists; pytest if `tests/` exists (fails without uv).
Suite: `uv run --with pytest --with httpx pytest -q tests`; no lint/build step.
`ock check` runs committed checks in a clean checkout; there is no hosted CI workflow (`ock ship` runs checks locally before opening the PR).
Run / demo: `uv run --script longform.py --help` prints commands without API calls.

## Layout
- `longform.py`: CLI, API, project state, branching trees, lore, prompts, deterministic checks.
- `scripts/`: check entry point; `tests/`: offline pytest suite.
- `openspec/`: behavior specs and changes; `docs/`: roadmap and ADRs.
- `.github/`: PR template; `myfic/`: private generated sample, never a test fixture.

## Rules
- Specs: `openspec/`. Decisions: `docs/adr/`. Plan: `docs/ROADMAP.md`.
- Keep `myfic/` and the third-party `56295265-LLam_ception-1.3.json` preset untracked.
- Never commit API keys or `.env`; synthetic test credentials only.
- Tests are offline/deterministic: no live API calls; use MockTransport/fakes and temporary projects.
- Keep the single-file CLI until an ADR-0002 trigger; extract only what tests need, preserving `uv run`.
