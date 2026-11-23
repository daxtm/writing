# Roadmap

## Goal

Make `longform.py` safe to change through observable offline regression tests,
then extract only the boundaries the prototype actually needs. Preserve
`uv run --script longform.py …` and existing project files and reports. Add a
local read-only browser window for all saved draft branches alongside the CLI.

## Out of scope

New generation features, browser editing/generation, remote hosting,
authentication/multi-user access, rich text, model/provider changes, live API
tests, private sample/preset fixtures, new dependencies, and speculative
packaging. Dependency provisioning may use network; test execution must not
contact external services.

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

## Phase 4 — Local read-only reader

- [ ] add-reader-gui — Keep active manuscript, every saved branch, and supporting writing readable in an automatically refreshed local browser.

Observe with `uv run --script longform.py view /path/to/project --no-browser --port 0`:
stdout prints `Reader: http://127.0.0.1:<assigned-port>/`. Open that URL to see
title/progress and scene links; select a scene to read the active manuscript,
full branch tree, inactive swipes, and metadata. Retained trees without current
scene cards remain linked. `/notes` shows the bible, continuity state, scene/arc
summaries, checks, and critiques as escaped plain text. Saving another draft
branch makes it appear on the next two-second refresh cycle without a terminal
reading command or export. Ctrl-C stops the reader.

ADR-0004 fixes the architecture: standard-library HTTP, literal loopback bind,
read-only content allowlist, trusted inline assets, and no build step. No
configuration secrets or arbitrary files are served. Tests use temporary
synthetic projects, `http.client`, and an ephemeral in-process listener under a
port-specific exception to the existing offline guard. `./scripts/check.sh`
discovers the reader tests and passes alongside the existing suite; no hosted
CI phase is introduced.

## Decisions

- [ADR-0001: Record architecture decisions](adr/0001-record-architecture-decisions.md).
- [ADR-0002: Keep the single-file CLI through the prototype](adr/0002-single-file-cli.md)
  accepted the prototype trade-off and defined extraction/package triggers;
  superseded by ADR-0003.
- [ADR-0003: Split the CLI into a package now](adr/0003-split-into-package.md)
  records the owner's deliberate override of the ADR-0002 gate and the package
  layout.
- [ADR-0004: Use a read-only standard-library local web reader](adr/0004-local-web-reader.md)
  records the local browser architecture and keeps browser mutation and remote
  access outside this feature.
