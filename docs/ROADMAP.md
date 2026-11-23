# Roadmap

## Goal

Make `longform.py` safe to change through observable offline regression tests,
then extract only the boundaries the prototype actually needs. Preserve
`uv run --script longform.py …` and existing project files and reports. Add a
native read-only desktop window for all saved draft branches alongside the CLI.

## Out of scope

New generation features, GUI editing/generation, browser/HTML interfaces, remote hosting,
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

## Phase 4 — Native read-only desktop reader

- [x] add-desktop-reader — Read active manuscript, every saved branch, and supporting notes in a native Tkinter/ttk window with position-preserving refresh.

Observe with
`uv run --script longform.py gui /path/to/project`: a native project-titled
read-only window opens and the command blocks until it closes. The left scene
list includes ID, title, status, words, and a separate retained-tree group.
Selecting a scene drives Manuscript (full active chain), Branches (every saved
node, including inactive descendants, full detail/history, parent/child
navigation), and Notes (project-wide bible, state, summaries, checks, critiques).
All writing is plain, selectable, scrollable text, not HTML or rich text.

Save another branch in the CLI: it appears on the next approximately two-second
auto-refresh, preserving selected scene/node, tab, and reading position. Toolbar
Refresh now/F5 forces a reload; Auto-refresh can be disabled. Status shows last
refresh time and current-project actual/target words. Ctrl+Q or window close
cancels the timer and returns to the terminal. No server, browser, provider
calls, editing controls, or configuration/credential viewer is introduced.

[ADR-0005](adr/0005-desktop-gui.md) fixes Tkinter/ttk and display-independent
allowlisted snapshots, with no new dependencies. The owner verified Tk 9.0.4
under uv-managed Python 3.13 and a working desktop display; system Python lacks
Tk libraries, so use the same uv runtime as the CLI. Snapshot/CLI tests always
run offline; withdrawn-window smoke tests run only with available Tk/display
and skip cleanly headless. `./scripts/check.sh` discovers both and must pass in
both environments without weakening the existing network guard.

The owner rejected the unimplemented HTML plan. Its `add-reader-gui` change was
deleted, not archived as shipped; ADR-0004 remains historical, superseded by
ADR-0005. This phase is a proposal only, not an implemented GUI.

## Decisions

- [ADR-0001: Record architecture decisions](adr/0001-record-architecture-decisions.md).
- [ADR-0002: Keep the single-file CLI through the prototype](adr/0002-single-file-cli.md)
  accepted the prototype trade-off and defined extraction/package triggers;
  superseded by ADR-0003.
- [ADR-0003: Split the CLI into a package now](adr/0003-split-into-package.md)
  records the owner's deliberate override of the ADR-0002 gate and the package
  layout.
- [ADR-0004: Use a read-only standard-library local web reader](adr/0004-local-web-reader.md)
  records the rejected, unimplemented browser architecture; superseded by
  ADR-0005.
- [ADR-0005: Use Tkinter and ttk for the native read-only desktop reader](adr/0005-desktop-gui.md)
  records the native toolkit, uv runtime requirement, read-only model/widget
  boundary, and headless/display testing trade-offs.
