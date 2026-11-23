# Roadmap

## Goal

Make `longform.py` safe to change through observable offline regression tests,
then extract only the boundaries the prototype actually needs. Preserve
`uv run --script longform.py …` and existing project files and reports.

## Out of scope

New writing features, model/provider changes, live API tests, a web UI, private
sample/preset fixtures, and speculative packaging. Dependency provisioning may
use network; test execution must not.

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

## Phase 3 — Package only when triggered

- [ ] split-cli-package — At an ADR-0002 trigger, move tested boundaries into a package while retaining the thin uv launcher.

This phase is gated, not automatic. Trigger when tests need a stable reusable
core that in-script helpers cannot reasonably provide, a second consumer needs
the core, or the script reaches approximately 3,000 lines. Tests merely existing
does not trigger a split. Use `api.py`, `project.py`, `lore.py`, `prompt.py`,
`checks.py`, and `cli.py`; keep `longform.py` as a thin PEP 723 launcher.

Observe with `uv run --script longform.py --help`, then
`uv run --with pytest --with httpx pytest -q tests` and `./scripts/check.sh`:
the same commands and regression outputs continue to work. A package sacrifices
standalone one-file portability even though the launcher command stays the same.

## Decisions

- [ADR-0001: Record architecture decisions](adr/0001-record-architecture-decisions.md).
- [ADR-0002: Keep the single-file CLI through the prototype](adr/0002-single-file-cli.md)
  accepts the prototype trade-off and defines extraction/package triggers.
- No additional durable decision is forced by the testing runner or local check
  setup; implementation details stay in the relevant change design.
