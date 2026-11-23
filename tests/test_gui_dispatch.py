"""Headless tests for the `gui DIR` dispatch (no Qt import, no display).

The dispatch must happen before Project construction, block until the window
closes (the injected fake application boundary records the order), and never
require a GUI toolkit for CLI help. Non-GUI commands stay unchanged.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

from longform_core import cli  # noqa: E402


def _child_env(tmp_path, strip_display=False):
    """Interpreter env with PySide6 and tkinter imports blocked."""
    blocker = tmp_path / "no-gui-toolkits"
    blocker.mkdir()
    (blocker / "sitecustomize.py").write_text(textwrap.dedent("""
        import sys
        sys.modules["PySide6"] = None
        sys.modules["tkinter"] = None
    """), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(blocker)
    for name in ("FEATHERLESS_API_KEY", "OPENAI_API_KEY"):
        env.pop(name, None)
    env.pop("QT_QPA_PLATFORM", None)
    if strip_display:
        for name in ("WAYLAND_DISPLAY", "WAYLAND_SOCKET", "DISPLAY"):
            env.pop(name, None)
    return env


def _child(argv, tmp_path, block_toolkits=True):
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(REPO)!r})\n"
        f"sys.argv = {argv!r}\n"
        "import longform\n"
        "raise SystemExit(longform.main() or 0)\n"
    )
    env = _child_env(tmp_path) if block_toolkits else dict(os.environ)
    return subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, env=env, timeout=120, cwd=str(REPO))


def test_cli_help_lists_gui_without_gui_toolkit(tmp_path):
    """Help works with GUI toolkits made unavailable and lists gui."""
    r = _child(["longform.py", "--help"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "gui" in r.stdout.split("status DIR")[0], "help must list the gui command"


def test_gui_dispatch_blocks_until_close(monkeypatch, tmp_path):
    """`gui DIR` builds/shows one window and blocks in app.exec() until close."""
    from longform_core import cli
    import longform_core.gui_window as gw

    calls = []

    class FakeApp:
        def __init__(self, *args, **kwargs):
            pass

        def platformName(self):
            return "wayland"

        def exec(self):
            calls.append("exec")
            return 7

    class FakeWindow:
        def __init__(self, dir_path, **kwargs):
            calls.append(("window", dir_path))

        def show(self):
            calls.append("show")

    monkeypatch.setattr(gw, "QApplication", FakeApp)
    monkeypatch.setattr(gw, "MainWindow", FakeWindow)

    def _no_project(*_a, **_k):
        raise AssertionError("gui must dispatch before Project construction")

    monkeypatch.setattr("longform_core.project.Project", _no_project)
    monkeypatch.setattr(sys, "argv", ["longform.py", "gui", str(tmp_path)])

    rc = cli.main()
    assert rc == 7
    assert calls == [("window", str(tmp_path)), "show", "exec"], \
        "window must be shown before the blocking app.exec()"


def test_gui_unsets_platform_env_selects_wayland(monkeypatch):
    """Unset QT_QPA_PLATFORM means Wayland: the env is set before Qt loads."""
    import longform_core.gui as gui
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    assert gui.resolve_platform() == "wayland"
    assert os.environ["QT_QPA_PLATFORM"] == "wayland"


def test_gui_refuses_explicit_fallback_platform(monkeypatch, tmp_path, capsys):
    """Any explicit non-'wayland' value (incl. fallback lists) fails early."""
    import longform_core.gui as gui
    import longform_core.gui_window
    monkeypatch.setenv("QT_QPA_PLATFORM", "wayland,xcb")
    monkeypatch.setattr(sys, "argv", ["longform.py", "gui", str(tmp_path)])
    monkeypatch.delitem(sys.modules, "longform_core.gui_window", raising=False)
    constructed = []
    monkeypatch.setattr(longform_core.gui_window, "QApplication",
                        lambda *a, **k: constructed.append("app"))
    rc = cli.main()
    assert rc == 1
    assert "wayland" in capsys.readouterr().err
    assert constructed == [], "no Qt application may start on a refused platform"
    assert "longform_core.gui_window" not in sys.modules


def test_gui_missing_qt_diagnostics(tmp_path):
    """Without PySide6, gui exits nonzero and recommends the uv command."""
    r = _child(["longform.py", "gui", str(tmp_path / "p")], tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "PySide6" in r.stderr
    assert "uv run --script longform.py gui" in r.stderr


def test_gui_wayland_unavailable_fails_with_guidance(tmp_path):
    """A real QApplication init without any display fails nonzero; the flushed
    pre-start guidance is printed even for plugin-level aborts."""
    import longform_core.gui_window as gw
    env = dict(os.environ)
    for name in ("WAYLAND_DISPLAY", "WAYLAND_SOCKET", "DISPLAY",
                 "FEATHERLESS_API_KEY", "QT_QPA_PLATFORM"):
        env.pop(name, None)
    r = subprocess.run([sys.executable, "-c",
                        "import sys\n"
                        f"sys.path.insert(0, {str(REPO)!r})\n"
                        f"sys.argv = {['longform.py', 'gui', str(tmp_path)]!r}\n"
                        "import longform\n"
                        "raise SystemExit(longform.main() or 0)\n"],
                       capture_output=True, text=True, env=env, timeout=60,
                       cwd=str(REPO))
    assert r.returncode != 0, r.stdout
    assert "native Wayland is required" in r.stdout + r.stderr
    # the guidance is emitted before QApplication construction in gw.run
    assert "PRE_START_GUIDANCE" in Path(gw.__file__).read_text(encoding="utf-8")


def test_gui_mismatched_platform_after_init(monkeypatch, tmp_path, capsys):
    """Qt initializing another platform fails after init; no window is shown."""
    import longform_core.gui as gui
    import longform_core.gui_window as gw

    class FakeApp:
        def __init__(self, *a, **k):
            pass

        def platformName(self):
            return "xcb"

        def exec(self):
            raise AssertionError("exec must not run for a mismatched platform")

    shown = []
    monkeypatch.setattr(gw, "QApplication", FakeApp)
    monkeypatch.setattr(gw, "MainWindow",
                        lambda *a, **k: shown.append(a))
    rc = gui.run_cli(str(tmp_path))
    assert rc == 1
    assert "wayland" in capsys.readouterr().err
    assert shown == []
