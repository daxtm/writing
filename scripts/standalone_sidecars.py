#!/usr/bin/env python3
"""Write dist/longform-build.json and dist/THIRD-PARTY-NOTICES.txt.

Build-only helper called by scripts/build-standalone.sh after PyInstaller has
produced the one-file executable. It inspects the actual archive (GUI modules,
Qt bindings, native libraries and Wayland plugins), checks that every required
native component resolves with ``ldd``, and records explicit inventory,
host-versus-bundled dependency boundaries, and license texts. Missing required
components or license materials are errors, never silent omissions.

The script runs inside the provisioned build environment, where PyInstaller,
PySide6 and every pinned distribution are installed; it is never bundled.
"""

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path

LICENSE_TEXT_NAMES = ("LGPL-3.0-only.txt", "GPL-2.0-only.txt", "GPL-3.0-only.txt")
GUI_LICENSE = "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"
PYSIDE_DISTRIBUTIONS = {"pyside6-essentials", "pyside6_essentials", "shiboken6"}

# Qt bindings and native components the workspace imports or starts.
REQUIRED_BINDINGS = (
    "PySide6/QtCore.abi3.so",
    "PySide6/QtGui.abi3.so",
    "PySide6/QtWidgets.abi3.so",
    "shiboken6/Shiboken.abi3.so",
)
REQUIRED_LIBRARY_PREFIXES = (
    "PySide6/Qt/lib/libQt6Core.so",
    "PySide6/Qt/lib/libQt6Gui.so",
    "PySide6/Qt/lib/libQt6Widgets.so",
    "PySide6/Qt/lib/libQt6WaylandClient.so",
    "PySide6/Qt/lib/libQt6WlShellIntegration.so",
    "PySide6/libpyside6.abi3.so",
    "shiboken6/libshiboken6.abi3.so",
)


class SidecarError(Exception):
    """A required component or material is missing; the build must fail."""


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, check=False, **kwargs)
    if result.returncode != 0:
        raise SidecarError(
            f"{' '.join(str(a) for a in args)} failed:\n"
            f"{result.stderr or result.stdout}")
    return result.stdout


# ---------------------------------------------------------------------------
# Archive inventory (pure inputs so tests can exercise the checks)
# ---------------------------------------------------------------------------

def gui_inventory(names):
    """Validate and describe the GUI parts of an archive name listing."""
    names = list(names)
    present = set(names)
    missing = [b for b in REQUIRED_BINDINGS if b not in present]
    for prefix in REQUIRED_LIBRARY_PREFIXES:
        if not any(n.startswith(prefix) for n in names):
            missing.append(prefix)
    if missing:
        raise SidecarError(
            "the archive is missing required GUI components: " + ", ".join(missing))

    plugins = sorted(n for n in names if n.startswith("PySide6/Qt/plugins/"))
    wayland_platforms = [n for n in plugins
                         if n.startswith("PySide6/Qt/plugins/platforms/")
                         and "libqwayland" in n]
    if not wayland_platforms:
        raise SidecarError(
            "the archive is missing the Qt Wayland platform plugin "
            "(PySide6/Qt/plugins/platforms/libqwayland*.so)")
    shell_plugins = [n for n in plugins if "wayland-shell-integration/" in n]
    if not any("xdg-shell" in n for n in shell_plugins):
        raise SidecarError("the archive is missing the xdg-shell Wayland plugin")
    decoration_plugins = [n for n in plugins if "wayland-decoration-client/" in n]
    graphics_plugins = [n for n in plugins if "wayland-graphics-integration-client/" in n]
    if not decoration_plugins:
        raise SidecarError("the archive is missing Wayland decoration plugins")
    if not graphics_plugins:
        raise SidecarError("the archive is missing Wayland graphics-integration plugins")

    def first(prefix):
        return next(n for n in names if n.startswith(prefix))

    return {
        "bindings": list(REQUIRED_BINDINGS),
        "libraries": {prefix.rsplit("/", 1)[-1]: first(prefix)
                      for prefix in REQUIRED_LIBRARY_PREFIXES},
        "plugins": plugins,
        "wayland_platform_plugins": wayland_platforms,
        "wayland_shell_plugins": sorted(shell_plugins),
        "wayland_decoration_plugins": sorted(decoration_plugins),
        "wayland_graphics_plugins": sorted(graphics_plugins),
    }


def required_native_entries(inventory):
    """Native files whose dynamic dependencies must be complete.

    Other collected Qt plugins are recorded in the inventory but not required
    on this Wayland-only path (for example the refused xcb/offscreen plugins).
    """
    entries = list(inventory["libraries"].values())
    entries += inventory["wayland_platform_plugins"]
    entries += inventory["wayland_shell_plugins"]
    entries += inventory["wayland_decoration_plugins"]
    entries += inventory["wayland_graphics_plugins"]
    return sorted(set(entries))


# ---------------------------------------------------------------------------
# Native dependency inspection
# ---------------------------------------------------------------------------

LDD_LINE = re.compile(r"^\s*(\S+) => (not found|\S+)(?:\s+\(0x[0-9a-f]+\))?\s*$")
LDD_SELF = re.compile(r"^\s*(\S+) \(0x[0-9a-f]+\)\s*$")


def parse_ldd(output):
    """Return {dependency: resolved_path_or_None} for ``ldd`` output."""
    deps = {}
    for line in output.splitlines():
        m = LDD_LINE.match(line)
        if m:
            name, target = m.group(1), m.group(2)
            deps[name] = None if target == "not found" else target
            continue
        m = LDD_SELF.match(line)
        if m:
            deps[m.group(1)] = m.group(1)
    return deps


def inspect_native_dependencies(entries, extract_root, ldd_runner=None):
    """Run ldd on each extracted native entry and split bundled from host.

    Any unresolved dependency is a build failure. Paths inside the extraction
    root are bundled; everything else remains a documented host dependency.
    """
    extract_root = Path(extract_root)
    ldd_runner = ldd_runner or (lambda path: run(["ldd", str(path)]))
    env_path = os.pathsep.join([str(extract_root), str(extract_root / "PySide6/Qt/lib")])
    records = {}
    bundled, host, unresolved = set(), set(), []
    for entry in entries:
        path = extract_root / entry
        if not path.is_file():
            raise SidecarError(f"native component was not extracted: {entry}")
        output = ldd_runner(path, env_path)
        deps = parse_ldd(output)
        file_bundled, file_host = [], []
        for name, target in sorted(deps.items()):
            if target is None:
                unresolved.append(f"{entry}: {name}")
                continue
            resolved = Path(target).resolve()
            if resolved == extract_root or extract_root in resolved.parents:
                bundled.add(name)
                file_bundled.append(name)
            else:
                host.add(name)
                file_host.append(name)
        records[entry] = {"bundled": file_bundled, "host": file_host}
    if unresolved:
        raise SidecarError(
            "unresolved native GUI dependencies (not bundled and not on the "
            "build host): " + ", ".join(unresolved))
    return {
        "inspected": sorted(entries),
        "bundled": sorted(bundled),
        "host": sorted(host),
        "files": records,
    }


def _ldd_with_path(path, library_path):
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = library_path
    return run(["ldd", str(path)], env=env)


# ---------------------------------------------------------------------------
# Extraction and sidecar generation
# ---------------------------------------------------------------------------

def _is_native_entry(name):
    base = name.rsplit("/", 1)[-1]
    if ".so" not in base:
        return False
    return (name.startswith("PySide6/") or name.startswith("shiboken6/")
            or "/" not in name)


def extract_native_entries(exe, dest):
    from PyInstaller.archive.readers import CArchiveReader

    reader = CArchiveReader(str(exe))
    extracted = []
    for name in reader.toc:
        if not _is_native_entry(name):
            continue
        path = Path(dest) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = reader.extract(name)
        if reader.toc[name][3] == 0:  # PyInstaller symlink entry
            target = data.rstrip(b"\x00").decode()
            target_path = Path(target)
            if not target_path.is_absolute():
                target_path = Path(dest) / target_path
            path.symlink_to(target_path)
        else:
            path.write_bytes(data)
            path.chmod(0o755)
        extracted.append(name)
    return sorted(extracted)


def collect_license_files(dist):
    """License files shipped inside a distribution, including licenses/."""
    files = []
    dist_path = Path(dist._path)
    lic_dir = dist_path / "licenses"
    if lic_dir.is_dir():
        files.extend(p for p in sorted(lic_dir.rglob("*")) if p.is_file())
    files.extend(p for p in sorted(dist_path.glob("*LICENSE*")) if p.is_file())
    return files


def load_vendored_licenses(license_dir):
    texts = {}
    for name in LICENSE_TEXT_NAMES:
        path = Path(license_dir) / name
        if not path.is_file():
            raise SidecarError(
                f"required license text missing: {path} "
                "(the pinned PySide6/Shiboken wheels ship no license files)")
        texts[name] = path.read_text(encoding="utf-8", errors="replace").strip()
    return texts


def bundled_resource_entries(root, archive_names):
    """Reviewed application-owned resources (ADR-0010) bundled into the
    archive: names and hashes only, never their contents. Missing resources
    fail the build; they are never silently omitted."""
    entries = []
    for res in sorted((Path(root) / "longform_core" / "resources").glob("*.json")):
        key = f"longform_core/resources/{res.name}"
        if key not in archive_names:
            raise SidecarError(
                f"bundled reviewed resource missing from the archive: {key} "
                "(add-data covers longform_core/resources)")
        entries.append({
            "path": key,
            "bytes": res.stat().st_size,
            "sha256": hashlib.sha256(res.read_bytes()).hexdigest(),
        })
    if not entries:
        raise SidecarError("no reviewed resources found under longform_core/resources")
    return entries


def build_documents(exe, root, license_dir):
    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import qVersion
    import shiboken6

    exe = Path(exe)
    root = Path(root)
    dist = exe.parent

    from PyInstaller.archive.readers import CArchiveReader
    names = list(CArchiveReader(str(exe)).toc)
    inventory = gui_inventory(names)

    # Bundled reviewed application-owned resources (ADR-0010): names and
    # hashes only, never their contents, in the informational sidecars.
    bundled_resources = bundled_resource_entries(root, names)

    vendored = load_vendored_licenses(license_dir)

    commit = run(["git", "rev-parse", "HEAD"], cwd=str(root)).strip()
    dirty_status = run(["git", "status", "--porcelain", "-uno"], cwd=str(root)).strip()
    glibc_line = run(["sh", "-c", "ldd --version 2>&1 | head -1"]).strip()
    ldd_out = run(["ldd", str(exe)]).strip()

    deps = {}
    for d in sorted(metadata.distributions(), key=lambda d: (d.metadata["Name"] or "").lower()):
        deps[d.metadata["Name"]] = d.version
    pyinstaller_version = next((v for k, v in deps.items() if k.lower() == "pyinstaller"), "")
    shiboken_version = shiboken6.__version__

    with tempfile.TemporaryDirectory(prefix="sidecar-native-", dir=str(root / "build")) as tmp:
        extracted = extract_native_entries(exe, tmp)
        required = [e for e in required_native_entries(inventory) if e in extracted]
        if len(required) != len(set(required_native_entries(inventory))):
            missing = sorted(set(required_native_entries(inventory)) - set(extracted))
            raise SidecarError("native components missing from extraction: "
                               + ", ".join(missing))
        native = inspect_native_dependencies(required, tmp, ldd_runner=_ldd_with_path)

    build_json = {
        "artifact": {
            "path": "dist/longform",
            "bytes": exe.stat().st_size,
            "sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
        },
        "source": {
            "commit": commit,
            "dirty": bool(dirty_status),
            "dirty_summary": dirty_status,
        },
        "platform": {"os": platform.system(), "arch": platform.machine(), "glibc": glibc_line},
        "interpreter": {"implementation": platform.python_implementation(),
                        "version": platform.python_version()},
        "dependencies": deps,
        "pyinstaller": {"version": pyinstaller_version, "mode": "onefile console",
                        "flags": os.environ.get("PYINSTALLER_FLAGS", "")},
        "gui": {
            "pyside6": pyside_version,
            "shiboken6": shiboken_version,
            "qt": qVersion(),
            "bindings_distribution": "pyside6-essentials",
            "license": GUI_LICENSE,
            "inventory": inventory,
            "native_dependency_inspection": native,
        },
        "bundled_resources": {
            "note": ("Application-owned reviewed sanitized defaults derived "
                     "read-only from a private local setup per ADR-0010; "
                     "bundled verbatim with init, never user data."),
            "files": bundled_resources,
        },
        "host_libraries": {"ldd_artifact": ldd_out, "ldd_version": glibc_line},
        "notices": "dist/THIRD-PARTY-NOTICES.txt",
        "note": ("Compatibility boundary observed on the build host; no older-distribution, "
                 "musl, other-OS or universal GUI support is claimed. Sidecar files are "
                 "informational and not required to run the executable."),
    }

    python_prefix = Path(sys.base_prefix)
    python_license = python_prefix / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}" / "LICENSE.txt"
    if not python_license.is_file():
        candidates = [c for c in python_prefix.rglob("LICENSE*")
                      if c.is_file() and "python" not in c.name]
        python_license = candidates[0] if candidates else None
    if python_license is None or not python_license.is_file():
        raise SidecarError("could not locate the Python runtime license text")

    out = []
    out.append("Third-party notices for the standalone longform executable")
    out.append("=========================================================")
    out.append("")
    out.append(f"Source revision: {commit}")
    out.append("Generated by scripts/build-standalone.sh. The executable bundles the")
    out.append("Python runtime, the application modules and CLI dependency closure, the")
    out.append("Qt GUI runtime (PySide6, Shiboken and Qt libraries/plugins) and certifi's")
    out.append("CA certificate data. The PyInstaller bootloader is distributed under")
    out.append("the GPL with the bootloader exception reproduced below.")
    out.append("")
    out.append("Bundled reviewed resources (application-owned, ADR-0010): init writes")
    out.append("these sanitized defaults verbatim; names and hashes only below, never")
    out.append("their contents.")
    out.append("")
    for res in bundled_resources:
        out.append(f"  {res['path']}  {res['bytes']} bytes  sha256={res['sha256']}")
    out.append("")

    def add_license(title, name, text):
        out.append("-" * 72)
        out.append(f"{title}  ({name})")
        out.append("-" * 72)
        out.append("")
        out.append(text)
        out.append("")

    add_license(f"Python {platform.python_version()} runtime ({platform.python_implementation()}), "
                "PSF License Agreement", python_license.name,
                python_license.read_text(encoding="utf-8", errors="replace").strip())

    for d in sorted(metadata.distributions(), key=lambda d: (d.metadata["Name"] or "").lower()):
        name = d.metadata["Name"]
        if name.lower().replace("_", "-") in PYSIDE_DISTRIBUTIONS:
            continue  # emitted with the native Qt component section below
        license_files = collect_license_files(d)
        if not license_files:
            raise SidecarError(f"no license text found for {name} {d.version}")
        for p in license_files:
            add_license(f"{name} {d.version}", p.name,
                        p.read_text(encoding="utf-8", errors="replace").strip())

    out.append("-" * 72)
    out.append("PySide6, Shiboken and Qt native components")
    out.append("-" * 72)
    out.append("")
    out.append(f"PySide6 {pyside_version} (pyside6-essentials {pyside_version})")
    out.append(f"Shiboken6 {shiboken_version}")
    out.append(f"Qt {qVersion()} native libraries and bundled plugins")
    out.append(f"License: {GUI_LICENSE}")
    out.append("")
    out.append("The pinned PySide6/Shiboken wheels declare this license in their")
    out.append("metadata but ship no license text. The canonical SPDX texts below are")
    out.append("vendored under scripts/standalone-licenses/. Bundled plugin inventory:")
    out.append("")
    for name in inventory["plugins"]:
        out.append(f"  {name}")
    out.append("")
    for name in LICENSE_TEXT_NAMES:
        add_license(f"Qt/PySide6/Shiboken {GUI_LICENSE}", name, vendored[name])

    return build_json, "\n".join(out) + "\n"


def write_sidecars(exe, root, out_dir=None, license_dir=None):
    exe = Path(exe)
    root = Path(root)
    out_dir = Path(out_dir) if out_dir else exe.parent
    license_dir = Path(license_dir) if license_dir else root / "scripts" / "standalone-licenses"
    out_dir.mkdir(parents=True, exist_ok=True)
    build_json, notices = build_documents(exe, root, license_dir)
    (out_dir / "longform-build.json").write_text(json.dumps(build_json, indent=2) + "\n",
                                                 encoding="utf-8")
    (out_dir / "THIRD-PARTY-NOTICES.txt").write_text(notices, encoding="utf-8")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: standalone_sidecars.py EXE", file=sys.stderr)
        return 2
    try:
        root = Path(os.environ.get("ROOT") or Path(__file__).resolve().parents[1])
        out_dir = os.environ.get("LONGFORM_SIDECAR_DIR")
        license_dir = os.environ.get("LONGFORM_LICENSE_DIR")
        write_sidecars(Path(argv[0]), root, out_dir=out_dir, license_dir=license_dir)
    except SidecarError as e:
        print(f"build-standalone: error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
