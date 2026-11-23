#!/usr/bin/env bash
# Build the standalone native executable: dist/longform (+ informational sidecars).
#
# Supported build host: Linux x86_64, glibc. Build prerequisites: uv (with a
# provisionable Python 3.11) and network access for provisioning build
# dependencies. The built application never installs or provisions anything.
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

echo "== build-standalone: provisioning Python 3.11 + pinned build closure"
# Provisioning may use the network; the built application cannot.
uv venv --clear --python 3.11 "$WORK/venv" 1>&2 || err "could not provision a Python 3.11 build environment (uv venv failed)"
PY="$WORK/venv/bin/python"
uv pip install --python "$PY" -r "$REQ" 1>&2 || err "could not install pinned build requirements from $REQ"
"$PY" -c 'import sys; assert sys.version_info[:2] == (3, 11), sys.version; import ssl' \
	|| err "provisioned build Python is unusable"

echo "== build-standalone: freezing longform.py with PyInstaller"
"$PY" -m PyInstaller \
	--onefile --console --name longform --clean --noconfirm --noupx --collect-data certifi \
	--distpath "$DIST" --workpath "$WORK" --specpath "$WORK" \
	longform.py 1>&2

EXE="$DIST/longform"
[ -f "$EXE" ] && [ -x "$EXE" ] || err "PyInstaller reported success but $EXE is missing or not executable"

echo "== build-standalone: smoke test"
"$EXE" --help >/dev/null || err "built executable failed to run --help"

echo "== build-standalone: writing compatibility sidecars"
ROOT="$ROOT" EXE="$EXE" PYINSTALLER_FLAGS="--onefile --console --name longform --clean --noconfirm --noupx --collect-data certifi" \
"$PY" - <<'PYEOF' || err "writing dist/longform-build.json or dist/THIRD-PARTY-NOTICES.txt failed"
import hashlib
import json
import os
import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path

root = Path(os.environ["ROOT"])
exe = Path(os.environ["EXE"])
dist = exe.parent

def sh(*args):
    r = subprocess.run(args, capture_output=True, text=True, cwd=str(root), check=False)
    if r.returncode != 0:
        sys.stderr.write(f"build-standalone: error: {' '.join(args)} failed:\n{r.stderr}")
        sys.exit(1)
    return r.stdout.strip()

commit = sh("git", "rev-parse", "HEAD")
dirty_status = sh("git", "status", "--porcelain", "-uno")
glibc_line = sh("sh", "-c", "ldd --version 2>&1 | head -1")
ldd_out = sh("ldd", str(exe))

deps = {}
for d in sorted(metadata.distributions(), key=lambda d: (d.metadata["Name"] or "").lower()):
    deps[d.metadata["Name"]] = d.version
pyinstaller_version = next((v for k, v in deps.items() if k.lower() == "pyinstaller"), "")

# ---- dist/longform-build.json -------------------------------------------------
build_json = {
    "artifact": {
        "path": "dist/longform",
        "bytes": exe.stat().st_size,
        "sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
    },
    "source": {
        "commit": commit,
        "dirty": bool(dirty_status.strip()),
        "dirty_summary": dirty_status.strip() if dirty_status.strip() else "",
    },
    "platform": {"os": platform.system(), "arch": platform.machine(), "glibc": glibc_line},
    "interpreter": {"implementation": platform.python_implementation(),
                    "version": platform.python_version()},
    "dependencies": deps,
    "pyinstaller": {"version": pyinstaller_version, "mode": "onefile console",
                    "flags": os.environ["PYINSTALLER_FLAGS"]},
    "host_libraries": {"ldd_artifact": ldd_out, "ldd_version": glibc_line},
    "notices": "dist/THIRD-PARTY-NOTICES.txt",
    "note": ("Compatibility boundary observed on the build host; no older-distribution, "
             "musl, other-OS or GUI support is claimed. Sidecar files are informational "
             "and not required to run the executable."),
}
(dist / "longform-build.json").write_text(json.dumps(build_json, indent=2) + "\n", encoding="utf-8")

# ---- dist/THIRD-PARTY-NOTICES.txt ---------------------------------------------
python_prefix = Path(sys.base_prefix)
python_license = python_prefix / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}" / "LICENSE.txt"
if not python_license.is_file():
    candidates = list(python_prefix.rglob("LICENSE*"))
    candidates = [c for c in candidates if c.is_file() and "python" not in c.name]
    python_license = candidates[0] if candidates else None
if python_license is None or not python_license.is_file():
    sys.stderr.write("build-standalone: error: could not locate the Python runtime license text\n")
    sys.exit(1)

site_packages = Path(next(p for p in sys.path if p.endswith("site-packages")))
out = []
out.append("Third-party notices for the standalone longform executable")
out.append("=========================================================")
out.append("")
out.append(f"Source revision: {commit}")
out.append("Generated by scripts/build-standalone.sh. The executable bundles the")
out.append("Python runtime, the application modules and the distributions listed")
out.append("below; certifi's CA certificate data is bundled data covered by the")
out.append("certifi license (Mozilla Public License 2.0). The PyInstaller bootloader")
out.append("is distributed under the GPL with the bootloader exception reproduced in")
out.append("the PyInstaller license text below.")
out.append("")

def add_license(title, path):
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    out.append("-" * 72)
    out.append(f"{title}  ({path.name})")
    out.append("-" * 72)
    out.append("")
    out.append(text)
    out.append("")

add_license(f"Python {platform.python_version()} runtime ({platform.python_implementation()}), "
            "PSF License Agreement", python_license)

for d in sorted(metadata.distributions(), key=lambda d: (d.metadata["Name"] or "").lower()):
    name = d.metadata["Name"]
    dist_info = d._path  # pathlib.Path of the .dist-info directory
    license_files = []
    lic_dir = dist_info / "licenses"
    if lic_dir.is_dir():
        for p in sorted(lic_dir.rglob("*")):
            if p.is_file():
                license_files.append(p)
    for p in sorted(dist_info.glob("*LICENSE*")):
        if p.is_file():
            license_files.append(p)
    if not license_files:
        sys.stderr.write(f"build-standalone: error: no license text found for {name} {d.version}\n")
        sys.exit(1)
    for p in license_files:
        add_license(f"{name} {d.version}", p)

(dist / "THIRD-PARTY-NOTICES.txt").write_text("\n".join(out), encoding="utf-8")
PYEOF

echo "$EXE"
