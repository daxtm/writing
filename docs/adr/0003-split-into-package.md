# ADR-0003: Split the CLI into a package now

- Status: Accepted
- Date: 2026-11-23
- Related: supersedes ADR-0002; docs/ROADMAP.md

## Context
`longform.py` has grown to 2,771 lines covering API streaming, project state,
branching drafts, lore, prompt assembly, and deterministic checks. Phase 2
pushed repeated extractions through one file, and the tests import in-script
helpers directly. ADR-0002 gated packaging behind triggers (a reusable core a
second consumer needs, a testability need, or roughly 3,000 lines); at the
2026-11-23 gate check none were met. The owner reviewed that note and asked to
execute the split anyway.

## Options
1. Stay single-file until an ADR-0002 trigger — keeps one-file distribution,
   but ignores the owner's explicit request and leaves navigation strained.
2. Split into a package now as a deliberate override — clearer module
   boundaries and direct imports for tests, at the cost of one-file portability.

## Decision
Choose option 2: move the implementation into a `longform_core/` package
(`config`, `utils`, `project`, `api`, `tree`, `lore`, `prompt`, `checks`,
`commands`, `cli`) and keep `longform.py` at the repo root as a thin PEP 723
launcher re-exporting the public names, so `uv run --script longform.py …`
stays the entry point and existing `import longform` code keeps working.

## Consequences
- Good: per-topic modules are easier to navigate and test; tests import and
  monkeypatch real modules instead of one 2,700-line namespace.
- Good: the launcher command is preserved; behavior, output, and file formats
  are unchanged (move-only refactor behind the existing suite).
- Bad: one-file portability is lost — shipping now requires the package
  directory next to the launcher.
- Bad: module boundaries still need review as the code grows; the ADR-0002
  size trigger is moot, but future structure decisions get their own ADRs.
