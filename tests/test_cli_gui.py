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
    longform.main()
    return capsys.readouterr()


def test_gui_dispatches_fake_launcher_before_project(
        tmp_path, fake_gui, forbidden_project, monkeypatch, capsys):
    project = tmp_path / "proj"
    project.mkdir()
    run_cli(monkeypatch, capsys, "gui", str(project))
    assert fake_gui == [str(project)], "gui must call the launcher exactly once with DIR"


def test_cli_help_lists_gui(monkeypatch, capsys):
    run_cli(monkeypatch, capsys, "--help")
    out = capsys.readouterr().out
    assert "gui DIR" in out
