"""Offline CLI regression: complete new-project defaults (project-defaults-full-init 1.1).

`init DIR` with no preset selection must create all six initial files (including
a usable `writer_preset.json`) and all seven initial directories, list the
preset in its `created:` line, and make no provider call. Runs against the real
CLI entry point; no network, no owner source files, no fixtures.
"""

import json
import sys

import pytest

import longform_core.cli as cli

INIT_FILES = ("project.json", "bible.md", "state.md", "scenes.json",
              "summaries.json", "writer_preset.json")
INIT_DIRS = ("trees", "outlines", "critiques", "checks", "state_history",
             "lorebooks", "bible_history")


def test_cli_init_without_preset_creates_complete_defaults(tmp_path, monkeypatch,
                                                           capsys):
    proj = tmp_path / "demo"
    monkeypatch.setattr(sys, "argv", ["longform.py", "init", str(proj)])

    import longform_core.api as api

    def _no_provider(*_a, **_k):
        raise AssertionError("init must not construct a provider client")

    monkeypatch.setattr(api, "Api", _no_provider)

    cli.main()
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines and lines[0] == f"project: {proj}"
    assert lines[1].startswith("created: ")
    assert "writer_preset.json" in lines[1], \
        "the default preset must be listed as created"

    for name in INIT_FILES:
        assert (proj / name).is_file(), name
    for d in INIT_DIRS:
        assert (proj / d).is_dir(), d
    assert not (proj / "limits.json").exists(), "init never fetches limits"
    assert not (proj / "calls.jsonl").exists(), "init makes no provider call"

    from longform_core.project import Project
    from longform_core.prompt import writer_sampling

    p = Project(proj)
    preset = p.preset()
    for k in ("instruct", "context", "sysprompt", "preset"):
        assert isinstance(preset[k], dict), k
    params, _extra, _ignored = writer_sampling(preset, lambda s: s)
    assert params, "the bundled preset must yield usable sampling parameters"


def test_cli_init_repeat_reports_nothing_created(tmp_path, monkeypatch, capsys):
    proj = tmp_path / "demo"
    monkeypatch.setattr(sys, "argv", ["longform.py", "init", str(proj)])
    cli.main()
    first = capsys.readouterr()
    assert "writer_preset.json" in first.out
    monkeypatch.setattr(sys, "argv", ["longform.py", "init", str(proj)])
    cli.main()
    out = capsys.readouterr().out
    assert out == (f"project: {proj}\n"
                   "created: (nothing; all files already exist)\n"
                   "next: set models in project.json, fill in bible.md, "
                   "put lorebooks in lorebooks/, then run limits\n")


MASTER = {"preset": {"temp": 0.9, "genamt": 400},
          "instruct": {"macro": True, "input_sequence": "\n",
                       "input_suffix": "\n", "output_sequence": "\n",
                       "stop_sequence": ""},
          "context": {"story_string": "", "chat_start": "## Chat\n",
                      "example_separator": "\n"},
          "sysprompt": {"content": "write well", "name": "sp"}}


def test_cli_init_explicit_preset_copies_exact_bytes(tmp_path, monkeypatch,
                                                     capsys):
    proj = tmp_path / "demo"
    src = tmp_path / "mine.json"
    src.write_text(json.dumps(MASTER), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["longform.py", "init", str(proj),
                                      "--preset", str(src)])
    cli.main()
    out = capsys.readouterr().out
    assert "warning" not in out
    assert "writer_preset.json" in out.splitlines()[1]
    assert (proj / "writer_preset.json").read_bytes() == src.read_bytes(), \
        "the explicit override is copied byte-identically"


def test_cli_init_existing_preset_survives_with_warning(tmp_path, monkeypatch,
                                                        capsys):
    proj = tmp_path / "demo"
    src = tmp_path / "mine.json"
    src.write_text(json.dumps(MASTER), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["longform.py", "init", str(proj)])
    cli.main()
    capsys.readouterr()
    kept = (proj / "writer_preset.json").read_bytes()
    monkeypatch.setattr(sys, "argv", ["longform.py", "init", str(proj),
                                      "--preset", str(src)])
    cli.main()
    out = capsys.readouterr().out
    assert "warning: writer_preset.json already exists; not overwritten" in out
    assert (proj / "writer_preset.json").read_bytes() == kept, \
        "an existing preset is never replaced"


def test_cli_init_failure_exits_nonzero_without_transcript(tmp_path,
                                                           monkeypatch,
                                                           capsys):
    proj = tmp_path / "demo"
    src = tmp_path / "bad.json"
    src.write_text("{nope", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["longform.py", "init", str(proj),
                                      "--preset", str(src)])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code not in (0, None), "failures exit nonzero"
    captured = capsys.readouterr()
    assert captured.out == "", "no success transcript on failure"
    assert "error: " in captured.err
    assert "not valid JSON" in captured.err
    assert "created before the error" in captured.err, \
        "partial work is reported truthfully"
    assert not (proj / "writer_preset.json").exists(), \
        "invalid explicit input never falls back to the bundle"


def test_cli_init_missing_preset_source_exits_nonzero(tmp_path, monkeypatch,
                                                      capsys):
    proj = tmp_path / "demo"
    monkeypatch.setattr(sys, "argv", ["longform.py", "init", str(proj),
                                      "--preset", str(tmp_path / "gone.json")])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code not in (0, None)
    err = capsys.readouterr().err
    assert "could not be read" in err or "not found" in err
    assert "gone.json" in err
