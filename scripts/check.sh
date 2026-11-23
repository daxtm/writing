#!/usr/bin/env bash
# Project checks — `ock check` runs this on a commit, CI runs it on every PR.
# Offline and deterministic: no live API calls, no network beyond uv fetching dependencies once.
#   1. Python syntax of the CLI.
#   2. CLI smoke test (imports httpx, parses args) when uv is available.
#   3. Test suite once tests/ exists (see openspec/changes/*test*).
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
	echo "== tests"
	uv run --with pytest --with httpx pytest -q tests
else
	echo "no tests/ yet: see docs/ROADMAP.md for the testing plan"
fi
