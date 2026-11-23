# ADR-0001: Record architecture decisions

- Status: Accepted
- Date: 2026-11-23

## Context
Decisions that outlive a single change (dependencies, data formats, architecture) get forgotten or
re-argued. OpenSpec records what each change does; it doesn't keep a log of why the project is shaped
the way it is.

## Decision
Keep a decision log in `docs/adr/`, one short record per significant decision, written by OpenCode in the
same branch as the work and accepted by merging its PR. Routine choices stay in `design.md`.

## Consequences
- Good: the reasons survive; agents check the log before re-deciding.
- Bad: a little extra writing per significant decision.
