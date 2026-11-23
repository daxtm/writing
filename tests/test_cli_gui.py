"""`gui DIR` CLI wiring: dispatch before shared Project construction, fake launcher."""

import sys
import types

import pytest

import longform
import longform_core.cli as cli_mod


@pytest.fixture
def fake_gui(monkeypatch):
    """A fake desktop launcher module injected as longform_core.gui."""
    calls = []
    mod = types.ModuleType("longform_core.gui")
    mod.launch = lambda directory: calls.append(directory)
    monkeypatch.setitem(sys.modules, "longform_core.gui", mod)
    return calls


@pytest.fixture
def forbidden_project(monkeypatch):
    def _fail(*_a, **_k):
        raise AssertionError("shared Project construction must be bypassed by gui")
    monkeypatch.setattr(cli_mod, "Project", _fail)


def run_cli(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["longform.py", *argv])
    try:
        longform.main()
    except SystemExit as e:
        if e.code not in (0, None):
            raise  # argparse --help exits 0; anything else is a real failure
    return capsys.readouterr()


def test_gui_dispatches_fake_launcher_before_project(
        tmp_path, fake_gui, forbidden_project, monkeypatch, capsys):
    project = tmp_path / "proj"
    project.mkdir()
    run_cli(monkeypatch, capsys, "gui", str(project))
    assert fake_gui == [str(project)], "gui must call the launcher exactly once with DIR"


def test_cli_help_lists_gui(monkeypatch, capsys):
    out = run_cli(monkeypatch, capsys, "--help").out
    assert "gui DIR" in out


# -- lifecycle and subprocess error paths ---------------------------------------

def test_gui_never_constructs_project_for_valid_dir(
        tmp_path, fake_gui, forbidden_project, monkeypatch, capsys):
    p = tmp_path / "proj"
    p.mkdir()
    run_cli(monkeypatch, capsys, "gui", str(p))
    assert fake_gui == [str(p)]


@pytest.fixture
def cli_run(tmp_path):
    """Run longform.py in a subprocess with optional import-time hooks."""
    import os
    import subprocess

    def run(*argv, sitecustomize=None, poison_tk=False, timeout=60):
        guard_dir = tmp_path / "guard"
        guard_dir.mkdir(exist_ok=True)
        if poison_tk:
            # a shadowing tkinter module that refuses to import
            (guard_dir / "tkinter.py").write_text(
                "raise ImportError('no Tk libraries')\n", encoding="utf-8")
        if sitecustomize is not None:
            (guard_dir / "sitecustomize.py").write_text(sitecustomize,
                                                        encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(guard_dir)
        for name in ("FEATHERLESS_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            env.pop(name, None)
        return subprocess.run([sys.executable, "longform.py", *argv],
                              capture_output=True, text=True, env=env,
                              cwd=os.getcwd(), timeout=timeout)

    return run


def test_cli_help_lists_gui_without_tk(tmp_path, cli_run):
    # tkinter import is poisoned; if help loaded Tk it would crash
    r = cli_run("--help", poison_tk=True)
    assert r.returncode == 0
    assert "gui DIR" in r.stdout


def test_gui_missing_tk_concise_error(tmp_path, cli_run):
    import reader_support as rs

    p = tmp_path / "proj"
    p.mkdir()
    rs.write_json(p / "project.json", {"title": "T", "target_words": 5,
                                       "api_key": "KEYSECRET"})
    r = cli_run("gui", str(p), poison_tk=True)
    assert r.returncode != 0
    assert "traceback" not in r.stderr.lower()
    assert "uv run --script longform.py gui" in r.stderr
    assert "KEYSECRET" not in r.stderr + r.stdout


def test_gui_display_failure_concise_error(tmp_path, cli_run):
    import reader_support as rs

    p = tmp_path / "proj"
    p.mkdir()
    rs.write_json(p / "project.json", {"title": "T", "target_words": 5})
    guard = (
        "import tkinter\n"
        "def _fail(*_a, **_k):\n"
        "    raise tkinter.TclError('no display name')\n"
        "tkinter.Tk = _fail\n"
    )
    r = cli_run("gui", str(p), sitecustomize=guard)
    assert r.returncode != 0
    assert "traceback" not in r.stderr.lower()
    assert "display" in r.stderr
    assert "longform.py gui" in r.stderr


def test_gui_invalid_project_concise_error(tmp_path, cli_run):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = cli_run("gui", str(empty))
    assert r.returncode != 0
    assert "traceback" not in r.stderr.lower()
    assert "project.json" in r.stderr


def test_gui_malformed_project_config_concise_error(tmp_path, cli_run):
    p = tmp_path / "proj"
    p.mkdir()
    (p / "project.json").write_text('{"title": 42, "target_words": 5}\n')
    r = cli_run("gui", str(p))
    assert r.returncode != 0
    assert "traceback" not in r.stderr.lower()
    assert "42" not in r.stderr, "raw values are never echoed"


def test_gui_fake_launcher_error_propagates(monkeypatch, capsys, tmp_path):
    """A failing launcher surfaces as a concise nonzero failure."""
    import pytest

    mod = types.ModuleType("longform_core.gui")

    def boom(_dir):
        raise SystemExit("gui: simulated startup failure")
    mod.launch = boom
    monkeypatch.setitem(sys.modules, "longform_core.gui", mod)
    monkeypatch.setattr(cli_mod, "Project",
                        lambda *a, **k: pytest.fail("must not construct"))
    monkeypatch.setattr(sys, "argv", ["longform.py", "gui", str(tmp_path)])
    with pytest.raises(SystemExit):
        longform.main()
