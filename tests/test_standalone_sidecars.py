"""Unit tests for the standalone sidecar generator's required-material checks.

These run in the source suite and do not need PyInstaller, PySide6 or the built
executable; the integration assertions against the real sidecars live in
tests/test_standalone.py.
"""

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "standalone_sidecars.py"

spec = importlib.util.spec_from_file_location("standalone_sidecars", SCRIPT)
sidecars = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidecars)


def test_gui_inventory_requires_wayland_plugin_and_qt_bindings():
    names = list(sidecars.REQUIRED_BINDINGS)
    names += list(sidecars.REQUIRED_LIBRARY_PREFIXES)
    with pytest.raises(sidecars.SidecarError, match="Wayland platform plugin"):
        sidecars.gui_inventory(names)
    names.append("PySide6/Qt/plugins/platforms/libqwayland.so")
    with pytest.raises(sidecars.SidecarError, match="xdg-shell"):
        sidecars.gui_inventory(names)
    names.append("PySide6/Qt/plugins/wayland-shell-integration/libxdg-shell.so")
    with pytest.raises(sidecars.SidecarError, match="decoration"):
        sidecars.gui_inventory(names)
    names.append("PySide6/Qt/plugins/wayland-decoration-client/libbradient.so")
    with pytest.raises(sidecars.SidecarError, match="graphics-integration"):
        sidecars.gui_inventory(names)
    names.append("PySide6/Qt/plugins/wayland-graphics-integration-client/libqt-plugin-wayland-egl.so")
    inventory = sidecars.gui_inventory(names)
    assert inventory["wayland_platform_plugins"] == [
        "PySide6/Qt/plugins/platforms/libqwayland.so"]
    assert "PySide6/Qt/plugins/wayland-shell-integration/libxdg-shell.so" in \
        inventory["wayland_shell_plugins"]


def test_gui_inventory_rejects_missing_qt_library():
    names = [n for n in sidecars.REQUIRED_BINDINGS]
    names += [p for p in sidecars.REQUIRED_LIBRARY_PREFIXES
              if "libQt6WaylandClient" not in p]
    with pytest.raises(sidecars.SidecarError, match="libQt6WaylandClient"):
        sidecars.gui_inventory(names)


def test_parse_ldd_distinguishes_resolved_and_missing():
    output = """\
\tlinux-vdso.so.1 (0x00007fff)
\tlibQt6Core.so.6 => /tmp/extract/PySide6/Qt/lib/libQt6Core.so.6 (0x00007f00)
\tlibc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x00007f01)
\tlibmissing.so.9 => not found
"""
    deps = sidecars.parse_ldd(output)
    assert deps["libQt6Core.so.6"].endswith("libQt6Core.so.6")
    assert deps["libc.so.6"].startswith("/lib/")
    assert deps["libmissing.so.9"] is None
    assert deps["linux-vdso.so.1"] == "linux-vdso.so.1"


def test_native_inspection_splits_bundled_host_and_fails_on_missing(tmp_path):
    root = tmp_path / "extract"
    lib = root / "PySide6/Qt/lib/libQt6Core.so.6"
    lib.parent.mkdir(parents=True)
    lib.write_bytes(b"\x7fELF")
    plugin = root / "PySide6/Qt/plugins/platforms/libqwayland.so"
    plugin.parent.mkdir(parents=True)
    plugin.write_bytes(b"\x7fELF")

    def ldd(path, library_path):
        assert str(root) in library_path
        return (f"\tlibQt6Core.so.6 => {lib} (0x1)\n"
                "\tlibwayland-client.so.0 => /lib/libwayland-client.so.0 (0x2)\n")

    result = sidecars.inspect_native_dependencies(
        ["PySide6/Qt/plugins/platforms/libqwayland.so"], root, ldd_runner=ldd)
    assert "libQt6Core.so.6" in result["bundled"]
    assert "libwayland-client.so.0" in result["host"]
    assert result["files"]["PySide6/Qt/plugins/platforms/libqwayland.so"]["host"] == [
        "libwayland-client.so.0"]

    def broken(path, library_path):
        return "\tlibmissing.so.9 => not found\n"

    with pytest.raises(sidecars.SidecarError, match="libmissing.so.9"):
        sidecars.inspect_native_dependencies(
            ["PySide6/Qt/plugins/platforms/libqwayland.so"], root, ldd_runner=broken)


def test_vendored_license_texts_are_required(tmp_path):
    with pytest.raises(sidecars.SidecarError, match="required license text missing"):
        sidecars.load_vendored_licenses(tmp_path)
    for name in sidecars.LICENSE_TEXT_NAMES:
        (tmp_path / name).write_text(f"text for {name}\n", encoding="utf-8")
    texts = sidecars.load_vendored_licenses(tmp_path)
    assert set(texts) == set(sidecars.LICENSE_TEXT_NAMES)


def test_bundled_resource_entries_match_repository():
    """The sidecar's resource provenance is computed from the reviewed
    repository assets and the archive TOC."""
    import hashlib
    root = REPO
    names = {f"longform_core/resources/{p.name}"
             for p in (root / "longform_core" / "resources").glob("*.json")}
    entries = sidecars.bundled_resource_entries(root, names)
    assert [e["path"] for e in entries] == \
        ["longform_core/resources/project_defaults.json",
         "longform_core/resources/writer_preset.json"]
    for e in entries:
        data = (root / e["path"]).read_bytes()
        assert e["bytes"] == len(data)
        assert e["sha256"] == hashlib.sha256(data).hexdigest()


def test_bundled_resource_entries_fail_closed(tmp_path):
    (tmp_path / "longform_core" / "resources").mkdir(parents=True)
    (tmp_path / "longform_core" / "resources" / "project_defaults.json") \
        .write_text("{}", encoding="utf-8")
    with pytest.raises(sidecars.SidecarError, match="missing from the archive"):
        sidecars.bundled_resource_entries(tmp_path, set())
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(sidecars.SidecarError, match="no reviewed resources found"):
        sidecars.bundled_resource_entries(empty,
                                          {"longform_core/resources/x.json"})
