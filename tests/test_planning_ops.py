"""Headless planning-operation tests (gui-project-planning 1.2+).

CLI/operation parity is byte-level: the shared operations produce the same
project files, inputs, histories and backups as the corresponding CLI flows
under fixed stamps/clocks, and the op results are sanitized (no secrets).
All offline: temp projects, synthetic presets, no network.
"""

import json
from pathlib import Path

import pytest

import longform_core.commands as commands
import longform_core.planning_operations as plan
from longform_core.draft_operations import OpError
from longform_core.utils import stamp

MASTER = {
    "preset": {"temp": 1.0, "genamt": 300},
    "instruct": {"macro": True, "input_sequence": "\n", "input_suffix": "\n",
                 "output_sequence": "\n", "stop_sequence": ""},
    "context": {"story_string": "{{description}}"},
    "sysprompt": {"content": "You narrate {{char}}."},
}


@pytest.fixture(autouse=True)
def fixed_stamp(monkeypatch):
    monkeypatch.setattr(commands, "stamp", lambda: "20260101-000000")
    monkeypatch.setattr(plan, "stamp", lambda: "20260101-000000")
    monkeypatch.setattr(plan, "now", lambda: "2026-01-01T00:00:00+00:00")


@pytest.fixture
def master_file(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "master.json").write_text(json.dumps(MASTER), encoding="utf-8")
    return src / "master.json"


def cli_init(root, preset=None, monkeypatch=None, capsys=None):
    args = type("A", (), {"dir": str(root), "preset": preset})()
    commands.cmd_init(args)
    return capsys.readouterr()


# ------------------------------------------------------------------ init

def test_init_matches_cli_files_and_transcript(tmp_path, monkeypatch, capsys):
    a, b = tmp_path / "cli", tmp_path / "op"
    out = cli_init(a, monkeypatch=monkeypatch, capsys=capsys).out
    plan.init_project(b)
    for name in plan.INIT_FILES:
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
    for d in plan.INIT_DIRS:
        assert (a / d).is_dir() and (b / d).is_dir()
    assert out == (f"project: {a}\n"
                   "created: project.json, bible.md, state.md, scenes.json, summaries.json\n"
                   "next: set models in project.json, fill in bible.md, put lorebooks in "
                   "lorebooks/, then run limits\n")


def test_init_with_preset_matches_cli(tmp_path, master_file, capsys):
    a, b = tmp_path / "cli", tmp_path / "op"
    cli_init(a, preset=str(master_file), capsys=capsys)
    plan.init_project(b, preset_src=str(master_file))
    assert (a / "writer_preset.json").read_bytes() == \
        (b / "writer_preset.json").read_bytes() == \
        master_file.read_bytes()


def test_init_repeated_fills_missing_only(tmp_path, master_file):
    root = plan.init_project(tmp_path / "p")
    (tmp_path / "p" / "project.json").write_text('{"title": "Mine"}\n',
                                                 encoding="utf-8")
    (tmp_path / "p" / "bible.md").unlink()
    again = plan.init_project(tmp_path / "p")
    assert again["created"] == ["bible.md"], "only the missing file is created"
    assert json.loads((tmp_path / "p" / "project.json").read_text()) \
        ["title"] == "Mine", "existing files are never replaced"


def test_init_collision_is_an_error_reporting_partial_work(tmp_path):
    root = tmp_path / "p"
    (root / "outlines").mkdir(parents=True)
    (root / "outlines" / "x.md").write_text("data", encoding="utf-8")
    (root / "trees").write_text("not a dir", encoding="utf-8")
    with pytest.raises(OpError) as e:
        plan.init_project(root)
    msg = str(e.value)
    assert "trees exists and is not a directory" in msg
    assert "project.json" in msg, "what was already created is reported"
    assert (root / "project.json").exists(), "earlier work is not undone"
    assert (root / "outlines" / "x.md").read_text() == "data"


def test_init_refuses_symlinked_target(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "bible.md").write_text("keep me", encoding="utf-8")
    root = tmp_path / "p"
    root.mkdir()
    (root / "bible.md").symlink_to(real / "bible.md")
    with pytest.raises(OpError) as e:
        plan.init_project(root)
    assert "symlink" in str(e.value)
    assert (real / "bible.md").read_text() == "keep me"


# --------------------------------------------------------------- presets

def test_import_preset_copies_unchanged_bytes(tmp_path, master_file):
    root = tmp_path / "p"
    root.mkdir()
    out = plan.import_preset(root, master_file)
    assert (root / "writer_preset.json").read_bytes() == master_file.read_bytes()
    assert out["imported"] == "writer_preset.json"


@pytest.mark.parametrize("payload,fragment", [
    ({"instruct": {}, "context": {}, "preset": {}}, "missing 'sysprompt'"),
    ("{nope", "not valid JSON"),
    ("[1, 2]", "not a SillyTavern master export (not a JSON object)"),
])
def test_import_preset_rejects_invalid_sources(tmp_path, payload, fragment):
    root = tmp_path / "p"
    root.mkdir()
    src = tmp_path / "bad.json"
    src.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                   encoding="utf-8")
    with pytest.raises(OpError) as e:
        plan.import_preset(root, src)
    assert fragment in str(e.value)
    assert not (root / "writer_preset.json").exists()


def test_import_preset_missing_source_is_an_error(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    with pytest.raises(OpError) as e:
        plan.import_preset(root, tmp_path / "absent.json")
    assert "could not be read" in str(e.value)


def test_import_preset_never_overwrites_destination(tmp_path, master_file):
    root = tmp_path / "p"
    root.mkdir()
    (root / "writer_preset.json").write_text('{"preset": {}}', encoding="utf-8")
    with pytest.raises(OpError) as e:
        plan.import_preset(root, master_file)
    assert "already exists; not overwritten" in str(e.value)
    assert (root / "writer_preset.json").read_text() == '{"preset": {}}'
    assert getattr(e.value, "collision", False), "GUI offers no Replace button"
    assert master_file.read_bytes() == json.dumps(MASTER).encode(), \
        "the external source is never modified"


def test_import_preset_refuses_symlink_destination(tmp_path, master_file):
    root = tmp_path / "p"
    root.mkdir()
    other = tmp_path / "other.json"
    other.write_text("{}", encoding="utf-8")
    (root / "writer_preset.json").symlink_to(other)
    with pytest.raises(OpError):
        plan.import_preset(root, master_file)
    assert other.read_text() == "{}"


# ----------------------------------------------------------------- open

def test_project_overview_states(tmp_path):
    missing = plan.project_overview(tmp_path / "nope")
    assert not missing["exists"] and not missing["config_ok"]
    assert "does not exist" in missing["warnings"][0]

    empty = plan.project_overview(tmp_path / "empty")
    empty = plan.project_overview((tmp_path / "empty"))
    (tmp_path / "empty").mkdir()
    empty = plan.project_overview(tmp_path / "empty")
    assert empty["exists"] and not empty["config_ok"]
    assert set(empty["missing_files"]) == set(plan._INIT_FILE_NAMES)

    built = plan.init_project(tmp_path / "p")
    over = plan.project_overview(tmp_path / "p")
    assert over["config_ok"] and over["scenes"] == 0
    assert over["missing_files"] == []
    assert set(over["dirs"]) == set(plan.INIT_DIRS)
    assert over["title"] == "Untitled"


def test_project_overview_invalid_config_reports_not_reset(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    (root / "project.json").write_text("{nope", encoding="utf-8")
    over = plan.project_overview(root)
    assert not over["config_ok"] and "not valid JSON" in over["warnings"][0]
    assert (root / "project.json").read_text() == "{nope", "files untouched"


def test_project_overview_never_exposes_secrets(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    sentinel = "sk-sentinel-inline-key"
    (root / "project.json").write_text(json.dumps(
        {"api_key": sentinel, "api_key_env": "FEATHERLESS_API_KEY"}),
        encoding="utf-8")
    over = plan.project_overview(root)
    blob = json.dumps(over)
    assert sentinel not in blob, "the inline key value is never returned"
    assert over["inline_key"] is True, "only boolean availability is shown"
    assert over["api_key_env"] == "FEATHERLESS_API_KEY"
    assert over["creds_ok"] is True


def test_project_overview_env_credential_availability(tmp_path, monkeypatch):
    root = tmp_path / "p"
    plan.init_project(root)
    over = plan.project_overview(root)
    assert over["api_key_env"] == "FEATHERLESS_API_KEY"
    assert over["env_set"] is False and over["creds_ok"] is False
    monkeypatch.setenv("FEATHERLESS_API_KEY", "sk-env")
    over = plan.project_overview(root)
    assert over["env_set"] is True and over["inline_key"] is False
    assert "sk-env" not in json.dumps(over)


def test_project_overview_unsafe_preset_path_is_not_read(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (root / "project.json").write_text(json.dumps(
        {"roles": {"writer": {"preset": "../outside.json"}}}), encoding="utf-8")
    over = plan.project_overview(root)
    assert over["preset_found"] is False
    assert "unsafe" in " ".join(over["warnings"])
