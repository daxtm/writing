#!/usr/bin/env bash
# Build the standalone native executable: dist/longform (+ informational sidecars).
#
# Supported build host: Linux x86_64, glibc. Build prerequisites: uv (with a
# provisionable Python 3.13) and network access for provisioning build
# dependencies. The built application never installs or provisions anything.
#
# The build interpreter must be CPython >= 3.12: PySide6 6.12.0 on CPython 3.11
# drops one reference to None on every Qt call, so any long-running GUI aborts
# with "Fatal Python error: none_dealloc: deallocating None". CPython 3.12+
# makes None immortal, which neutralises that binding bug; PySide6 6.12.0 has
# no patch release that fixes it.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
REQ="scripts/standalone-requirements.txt"
DIST="$ROOT/dist"
WORK="$ROOT/build/standalone"

err() {
	echo "build-standalone: error: $*" >&2
	exit 1
}

command -v uv >/dev/null 2>&1 || err "uv not found: install uv (https://docs.astral.sh/uv/) to provision the build environment"
[ "$(uname -s)" = "Linux" ] || err "unsupported OS: $(uname -s) (this build targets Linux x86_64 glibc)"
[ "$(uname -m)" = "x86_64" ] || err "unsupported architecture: $(uname -m) (this build targets Linux x86_64)"
if ! { ldd --version 2>&1 | head -1 || true; } | grep -qi "glibc\|GNU libc"; then
	err "unsupported libc: $(ldd --version 2>&1 | head -1) (this build targets glibc, not musl)"
fi
[ -f "$REQ" ] || err "missing pinned build requirements: $REQ"

echo "== build-standalone: provisioning Python 3.13 + pinned build closure"
# Provisioning may use the network; the built application cannot.
uv venv --clear --python 3.13 "$WORK/venv" 1>&2 || err "could not provision a Python 3.13 build environment (uv venv failed)"
PY="$WORK/venv/bin/python"
uv pip install --python "$PY" -r "$REQ" 1>&2 || err "could not install pinned build requirements from $REQ"
"$PY" -c 'import sys; assert sys.version_info[:2] >= (3, 12), sys.version; import ssl' \
	|| err "provisioned build Python is unusable (CPython >= 3.12 required)"

echo "== build-standalone: freezing longform.py with PyInstaller"
"$PY" -m PyInstaller \
	--onefile --console --name longform --clean --noconfirm --noupx --collect-data certifi \
	--add-data "$ROOT/longform_core/resources:longform_core/resources" \
	--distpath "$DIST" --workpath "$WORK" --specpath "$WORK" \
	longform.py 1>&2

EXE="$DIST/longform"
[ -f "$EXE" ] && [ -x "$EXE" ] || err "PyInstaller reported success but $EXE is missing or not executable"

echo "== build-standalone: smoke test"
"$EXE" --help >/dev/null || err "built executable failed to run --help"

echo "== build-standalone: writing compatibility sidecars"
ROOT="$ROOT" PYINSTALLER_FLAGS="--onefile --console --name longform --clean --noconfirm --noupx --collect-data certifi --add-data $ROOT/longform_core/resources:longform_core/resources" \
"$PY" scripts/standalone_sidecars.py "$EXE" || err "writing dist/longform-build.json or dist/THIRD-PARTY-NOTICES.txt failed"

echo "$EXE"
