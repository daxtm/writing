"""Offline CLI regression: complete new-project defaults (project-defaults-full-init 1.1).

`init DIR` with no preset selection must create all six initial files (including
a usable `writer_preset.json`) and all seven initial directories, list the
preset in its `created:` line, and make no provider call. Runs against the real
CLI entry point; no network, no owner source files, no fixtures.
"""

import sys

import pytest

import longform_core.cli as cli

INIT_FILES = ("project.json", "bible.md", "state.md", "scenes.json",
              "summaries.json", "writer_preset.json")
INIT_DIRS = ("trees", "outlines", "critiques", "checks", "state_history",
             "lorebooks", "bible_history")


@pytest.mark.xfail(reason="baseline: CLI init without --preset creates no "
                          "writer_preset.json (project-defaults-full-init 1.1); "
                          "strict marker removed when initialization is extended",
                   strict=True)
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
