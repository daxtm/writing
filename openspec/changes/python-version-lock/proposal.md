# Proposal

## Why

“The python version should never drift. Fix the python drift, and fix the crash in the standalone.”

Commit `dd9803e` on `feat/guided-workflow` already fixes the reported standalone crash by moving its build to Python 3.13, requiring at least 3.12, and testing Qt/None-reference churn. However, a minor-version request and a lower bound still allow interpreter changes between source runs, checks, and rebuilds without review.

## What Changes

- Preserve `dd9803e` as an implementation prerequisite; do not redo its floor fix or existing regression.
- Pin ordinary CPython **3.13.15**, the interpreter recorded by the existing local build, including its patch version.
- Make source launch, syntax checks, both test phases, and freezing agree with one authoritative pin. Reject unavailable or mismatched interpreters instead of falling back.
- Extend the existing build metadata, artifact-reuse checks, and tests to enforce the pin and retain the crash regression.

Fix the existing launcher/build/check entry points rather than add a parallel runner. A new `.python-version` is necessary because no existing file owns a shared exact interpreter selection.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `standalone-distribution`: freeze only the reviewed exact interpreter; reject stale or mismatched build evidence.
- `offline-regression`: run source/check processes on that same interpreter and detect pin/metadata disagreement.

## Impact

Existing launcher metadata, build/check scripts, sidecars, regression fixtures, and runtime documentation change; ADR-0013 records the version policy.

**Out of scope:** dependency upgrades, a new packager, bit-identical binaries, additional platforms, GUI redesign, shipping, or claiming pending real Wayland acceptance.

**See it work:** `./scripts/check.sh` prints `== python: CPython 3.13.15`, runs the mandatory suites, and exits 0; `dist/longform-build.json` records that same interpreter.
