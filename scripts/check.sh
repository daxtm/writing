#!/usr/bin/env bash
# Bootstrap check for a documentation-only scaffold. Replace it with the project's test/build command when adding code.
set -euo pipefail
cd "$(dirname "$0")/.."
while IFS= read -r -d '' file; do
	case "$file" in
	*.md|*.txt|.gitignore|.github/*|openspec/*|scripts/check.sh) ;;
	*) echo "Wire the real checks for $file into scripts/check.sh" >&2; exit 1 ;;
	esac
done < <(git ls-files -z)
test -s AGENTS.md && test -s openspec/config.yaml
