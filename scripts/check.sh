#!/usr/bin/env bash
# Project checks — `ock check` runs this on a commit, CI runs it on every PR.
# Offline and deterministic: no live API calls; only interpreter provisioning,
# dependency provisioning and the standalone build may use the network. The
# built application and the test processes are network-guarded and must never
# reach it.
#
# Shared interpreter policy (ADR-0013): the root `.python-version` pins the
# reviewed CPython minor at 3.13. This entry point provisions the latest
# available managed 3.13 patch, verifies implementation and minor, reports the
# actual full version, and passes the same explicit request to every phase:
#   1. Python syntax of the CLI.
#   2. CLI smoke test (imports httpx, parses args).
#   3. Standalone: build the native executable once (provisioning build deps
#      through scripts/build-standalone.sh) and run the frozen-process tests,
#      including the frozen GUI discovery/archive/startup-policy coverage.
#      Requires uv and a C compiler for the test-only native network guard;
#      never skipped.
#   4. Source regression suite (offline; frozen executable tests are excluded
#      here because they already ran in step 3 against the built artifact).
# Host Python, active environments and a conflicting UV_PYTHON cannot change
# the selection, and there is no fallback interpreter: missing uv, a
# missing/malformed pin, another minor or implementation, or a provisioning
# failure exits nonzero before syntax compilation or any suite can pass.
set -euo pipefail
cd "$(dirname "$0")/.."

err() {
	echo "check: error: $*" >&2
	exit 1
}

# The pin is the single authority. Anything that is not a clean minor request
# (patch-specific, a range, a variant suffix or a non-CPython implementation)
# is a checkout bug: patch updates stay automatic and a minor bump is one
# reviewed pin/mirror change.
PIN_FILE=".python-version"
[ -f "$PIN_FILE" ] || err "missing $PIN_FILE: the authoritative CPython minor pin is required (see docs/adr/0013-cpython-minor-runtime-pin.md)"
REQUEST="$(cat "$PIN_FILE")"
case "$REQUEST" in
	cpython@3.13) : ;;
	*) err "invalid $PIN_FILE: '$REQUEST' (expected exactly 'cpython@3.13'; patch versions are chosen automatically and a minor bump is a reviewed pin/mirror change)" ;;
esac

command -v uv >/dev/null 2>&1 || err "uv not found: install uv (https://docs.astral.sh/uv/) — checks cannot select and verify $REQUEST without it"

# Provisioning may use the network; the test processes cannot. --upgrade takes
# the latest patch the resolver offers without any policy edit.
uv python install --upgrade "$REQUEST" || err "could not provision the requested interpreter ($REQUEST): update uv and check its provisioning resolver, then retry"

# Verify implementation and minor before any phase runs on a fallback.
PYQUERY='import platform; print(platform.python_implementation() + " " + platform.python_version())'
REPORT="$(uv run --no-project --python "$REQUEST" --managed-python python -c "$PYQUERY")" \
	|| err "could not verify the requested interpreter ($REQUEST): uv run failed"
IMPL="${REPORT%% *}"; FULLVER="${REPORT#* }"
[ "$IMPL" = "CPython" ] || err "requested $REQUEST but uv selected $IMPL ($FULLVER): refusing to check on another implementation"
case "$FULLVER" in
	3.13.*) ;;
	*) err "requested $REQUEST but the selected interpreter is $FULLVER: refusing to check on another minor" ;;
esac
echo "== python: CPython $FULLVER"

echo "== syntax"
uv run --no-project --python "$REQUEST" --managed-python python -m py_compile longform.py

echo "== cli smoke"
uv run --python "$REQUEST" --managed-python --script longform.py --help >/dev/null

if [ -d tests ]; then
	echo "== standalone"
	bash scripts/build-standalone.sh >/dev/null
	uv run --no-project --python "$REQUEST" --managed-python --with pytest --with httpx pytest -q tests/test_standalone.py
	echo "== tests"
	uv run --no-project --python "$REQUEST" --managed-python --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' pytest -q tests --ignore=tests/test_standalone.py
else
	echo "no tests/ yet: see docs/ROADMAP.md for the testing plan"
fi
