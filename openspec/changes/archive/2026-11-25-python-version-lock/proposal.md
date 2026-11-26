# Proposal

## Why

“The python version should never drift. Fix the python drift, and fix the crash in the standalone.”

Commit `dd9803e` on `feat/guided-workflow` already fixes the reported standalone crash by moving its build to Python 3.13, requiring at least 3.12, and testing Qt/None-reference churn. Source metadata and independently selected check interpreters still permit unintended minor-version drift. The owner chose to hold the CPython minor at 3.13 while accepting patch updates automatically.

## What Changes

- Preserve `dd9803e` as an implementation prerequisite; leave its independent CPython >=3.12 assertion and Qt/None-refcount regression unchanged.
- Set authoritative `.python-version` to `cpython@3.13` and PEP 723 `requires-python` to `>=3.13,<3.14`; never pin a patch.
- Make build/check provisioning resolve the latest available 3.13 patch automatically (currently 3.13.15), then explicitly select and verify CPython 3.13.x in every phase. Reject other minors or implementations.
- Record the requested minor and actual full version in existing build metadata; invalidate cached artifacts with a different actual minor, not a different 3.13 patch.

Fix existing launcher/build/check entry points, not a parallel runner. A new `.python-version` is necessary because no existing file owns their shared interpreter policy. Only a minor bump requires a reviewed pin/mirror change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `standalone-distribution`: freeze the reviewed CPython minor with automatic patch updates and minor-aware cache validation.
- `offline-regression`: keep source/check processes within that minor and detect pin/mirror disagreement.

## Impact

Existing launcher metadata, build/check scripts, sidecars, regression fixtures, and runtime documentation change; ADR-0013 records the version policy.

**Out of scope:** dependency upgrades, a new packager, bit-identical binaries, additional platforms, GUI redesign, shipping, or claiming pending real Wayland acceptance.

**See it work:** `./scripts/check.sh` reports `== python: CPython 3.13.<patch>`, runs mandatory suites, and exits 0; the sidecar records `cpython@3.13` and the actual full version.
