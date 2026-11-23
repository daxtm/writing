# ADR-0002: Keep the single-file CLI through the prototype

- Status: Accepted
- Date: 2026-11-23
- Related: add-test-suite; docs/ROADMAP.md

## Context
`longform.py` is a 2,673-line Python 3.11+ CLI with PEP 723 inline dependencies.
It combines API streaming, project files, branching drafts, lore, prompt assembly,
and deterministic text checks. `uv run --script longform.py` is the existing entry
point. An offline test suite is planned; there is no second consumer today.

## Options
1. Keep one script during the prototype, extracting small pure helpers in place —
   preserves single-file distribution and avoids import churn, but navigation and
   test isolation remain less convenient.
2. Split into a package now — clearer boundaries and stable imports, but introduces
   packaging/import decisions before tests protect behavior and changes how the
   single-file entry point is distributed.

## Decision
Choose option 1: first establish offline tests, keeping the existing script runner
and minimizing structural change before behavior is protected. Extract the
deterministic checker, card/lore parsing, and prompt assembly first, only as needed;
initial extractions stay inside `longform.py`.

Split when any trigger is met: tests need a stable reusable core interface that
in-script helpers cannot reasonably provide; a second consumer needs that core;
or the script reaches approximately 3,000 lines. Merely adding tests does not
automatically trigger packaging. At that point separate `api.py`, `project.py`,
`lore.py`, `prompt.py`, `checks.py`, and `cli.py` inside a package, retaining a thin
PEP 723 launcher supporting `uv run --script longform.py`.

## Consequences
- Good: preserves portable single-file execution during the prototype; tests can
  protect existing behavior before module boundaries move.
- Good: explicit triggers prevent both speculative packaging and indefinite growth.
- Bad: navigation, broad imports, and monkeypatching remain awkward in one file;
  Python tests need the repository root on `sys.path`.
- Bad: the eventual package will require adjacent files, so the thin launcher
  preserves the command, not standalone one-file portability. Migration and import
  maintenance are deferred, not eliminated; the approximate size trigger needs review.
