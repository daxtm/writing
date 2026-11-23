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


def _child_env(tmp_path):
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
