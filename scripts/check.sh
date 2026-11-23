#!/usr/bin/env bash
# Project checks — `ock check` runs this on a commit, CI runs it on every PR.
# Offline and deterministic: no live API calls; only dependency provisioning and
# the standalone build may use the network. The built application and the test
# processes are network-guarded and must never reach it.
#   1. Python syntax of the CLI.
#   2. CLI smoke test (imports httpx, parses args) when uv is available.
#   3. Standalone: build the native executable once (provisioning build deps
#      through scripts/build-standalone.sh) and run the frozen-process tests,
#      including the frozen GUI discovery/archive/startup-policy coverage.
#      Requires uv and a C compiler for the test-only native network guard;
#      never skipped.
#   4. Source regression suite (offline; frozen executable tests are excluded
#      here because they already ran in step 3 against the built artifact).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== syntax"
python3 -m py_compile longform.py

if command -v uv >/dev/null 2>&1; then
	echo "== cli smoke"
	uv run --script longform.py --help >/dev/null
else
	echo "uv not found: skipping CLI smoke test (syntax still checked)" >&2
fi

if [ -d tests ]; then
	if ! command -v uv >/dev/null 2>&1; then
		echo "tests/ exists but uv is unavailable; install uv to run the suite" >&2
		exit 1
	fi
	echo "== standalone"
	bash scripts/build-standalone.sh >/dev/null
	uv run --with pytest --with httpx pytest -q tests/test_standalone.py
	echo "== tests"
	uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' pytest -q tests --ignore=tests/test_standalone.py
else
	echo "no tests/ yet: see docs/ROADMAP.md for the testing plan"
fi
