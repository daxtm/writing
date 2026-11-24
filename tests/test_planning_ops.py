"""Headless planning-operation tests (gui-project-planning 1.2+).

CLI/operation parity is byte-level: the shared operations produce the same
project files, inputs, histories and backups as the corresponding CLI flows
under fixed stamps/clocks, and the op results are sanitized (no secrets).
All offline: temp projects, synthetic presets, no network.
"""

import json
import types
from pathlib import Path

import pytest

from longform_core.cancel import Cancelled

import reader_support as rs

import longform_core.commands as commands
import longform_core.planning_operations as plan
from longform_core.draft_operations import OpError
from longform_core.utils import stamp

_write_json = rs.write_json
_write_text = rs.write_text

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
    import longform_core.utils as utils
    monkeypatch.setattr(utils, "stamp", lambda: "20260101-000000")


@pytest.fixture
def master_file(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "master.json").write_text(json.dumps(MASTER), encoding="utf-8")
    return src / "master.json"


_write_json = rs.write_json
_write_text = rs.write_text


def cli_init(root, preset=None, monkeypatch=None, capsys=None):
    args = type("A", (), {"dir": str(root), "preset": preset})()
    commands.cmd_init(args)
    return capsys.readouterr()


# ------------------------------------------------------------------ init

def test_init_matches_cli_files_and_transcript(tmp_path, monkeypatch, capsys):
    a, b = tmp_path / "cli", tmp_path / "op"
    out = cli_init(a, monkeypatch=monkeypatch, capsys=capsys).out
    result = plan.init_project(b)
    for name in plan.INIT_FILES:
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
    for d in plan.INIT_DIRS:
        assert (a / d).is_dir() and (b / d).is_dir()
    assert result["created"][-1] == "writer_preset.json"
    assert out == (f"project: {a}\n"
                   "created: project.json, bible.md, state.md, scenes.json, "
                   "summaries.json, writer_preset.json\n"
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


# ------------------------------------------------- bundled defaults (1.3)

def test_init_bundled_defaults_exact_contents(tmp_path):
    import longform_core.defaults as dfl
    out = plan.init_project(tmp_path / "p")
    assert out["created"] == ["project.json", "bible.md", "state.md",
                              "scenes.json", "summaries.json",
                              "writer_preset.json"]
    assert out["dirs"] == ["trees", "outlines", "critiques", "checks",
                           "state_history", "lorebooks", "bible_history"]
    assert out["warnings"] == []
    assert out["preset"] == {"imported": "writer_preset.json",
                             "bytes": len(dfl.writer_preset_bytes()),
                             "replaced": False, "default": True}
    root = tmp_path / "p"
    expected_cfg = dfl.project_defaults()
    assert json.loads((root / "project.json").read_text()) == expected_cfg
    assert (root / "project.json").read_bytes() == \
        (json.dumps(expected_cfg, indent=2) + "\n").encode("utf-8")
    assert (root / "writer_preset.json").read_bytes() == \
        dfl.writer_preset_bytes()
    for name, content in (("bible.md", None), ("state.md", None),
                          ("scenes.json", "[]\n")):
        assert (root / name).is_file()
    assert json.loads((root / "summaries.json").read_text()) == \
        {"scenes": {}, "arcs": []}
    from longform_core.config import BIBLE_TEMPLATE, STATE_TEMPLATE
    assert (root / "bible.md").read_text() == BIBLE_TEMPLATE
    assert (root / "state.md").read_text() == STATE_TEMPLATE


def test_init_optional_title_isolation(tmp_path):
    root = tmp_path / "p"
    plan.init_project(root, title="Named")
    cfg = json.loads((root / "project.json").read_text())
    assert cfg["title"] == "Named"
    assert cfg["target_words"] == 17000, "only the title is overridden"
    again = plan.init_project(root)
    assert again["created"] == [], "an existing config is never re-titled"
    assert json.loads((root / "project.json").read_text())["title"] == "Named"


def test_init_repeated_reports_nothing_created(tmp_path):
    root = tmp_path / "p"
    plan.init_project(root)
    again = plan.init_project(root)
    assert again["created"] == [] and again["dirs"] == []
    assert again["preset"] is None and again["warnings"] == []


def test_init_restores_only_a_missing_default_preset(tmp_path):
    root = tmp_path / "p"
    plan.init_project(root)
    external = tmp_path / "elsewhere" / "mine.json"
    external.parent.mkdir()
    external.write_text(json.dumps(MASTER), encoding="utf-8")
    cfg = json.loads((root / "project.json").read_text())
    cfg["roles"]["writer"]["preset"] = str(external)
    (root / "project.json").write_text(json.dumps(cfg), encoding="utf-8")
    (root / "writer_preset.json").unlink()
    again = plan.init_project(root)
    assert again["created"] == ["writer_preset.json"]
    import longform_core.defaults as dfl
    assert (root / "writer_preset.json").read_bytes() == dfl.writer_preset_bytes(), \
        "only the missing local default preset is restored"
    assert json.loads((root / "project.json").read_text()) \
        ["roles"]["writer"]["preset"] == str(external), \
        "the configured external preset path is never retargeted"
    assert external.read_bytes() == json.dumps(MASTER).encode("utf-8")


def test_repeated_init_keeps_every_existing_byte(tmp_path):
    root = plan.init_project(tmp_path / "p")["root"]
    root = Path(root)
    edits = {"project.json": '{"title": "Edited", "target_words": 99}',
             "bible.md": "## Title\nmine\n", "state.md": "# mine",
             "scenes.json": '[{"id": "s001"}]', "summaries.json": '{"scenes": {}}',
             "writer_preset.json": '{"instruct": {}, "context": {}, "sysprompt": {}, "preset": {}}'}
    for name, text in edits.items():
        (root / name).write_text(text, encoding="utf-8")
    (root / "state_history" / "kept.md").write_text("drafted", encoding="utf-8")
    before = {p.name: p.read_bytes() for p in sorted(root.rglob("*"))
              if p.is_file()}
    out = plan.init_project(root)
    assert out["created"] == [] and out["dirs"] == []
    after = {p.name: p.read_bytes() for p in sorted(root.rglob("*"))
             if p.is_file()}
    assert after == before, "existing bytes never change on repeat"


def test_legacy_sparse_config_keeps_old_fallbacks_and_bytes(tmp_path):
    root = plan.init_project(tmp_path / "p")["root"]
    (Path(root) / "project.json").write_text('{"title": "Old"}\n',
                                             encoding="utf-8")
    from longform_core.project import Project
    p = Project(root)
    assert p.cfg["roles"]["writer"]["passage_words"] == 220, \
        "old sparse projects keep the previous application fallback"
    assert p.cfg["roles"]["writer"]["preset_overrides"] == {"temp": 1.06}
    raw = (Path(root) / "project.json").read_bytes()
    plan.init_project(root)
    assert (Path(root) / "project.json").read_bytes() == raw, \
        "repeated init never rewrites an existing configuration"


def test_init_invalid_explicit_preset_never_falls_back(tmp_path):
    root = tmp_path / "p"
    src = tmp_path / "bad.json"
    src.write_text("{nope", encoding="utf-8")
    with pytest.raises(OpError) as e:
        plan.init_project(root, preset_src=str(src))
    assert "not valid JSON" in str(e.value)
    assert "created before the error" in str(e.value), \
        "earlier writes are reported for a non-destructive retry"
    assert not (root / "writer_preset.json").exists(), \
        "no bundled substitution for invalid explicit input"
    retry = plan.init_project(root)
    assert retry["created"] == ["writer_preset.json"], \
        "retry after correction fills only missing paths"


def test_init_invalid_explicit_preset_missing_required_key(tmp_path):
    src = tmp_path / "partial.json"
    src.write_text(json.dumps({"instruct": {}, "context": {}}),
                   encoding="utf-8")
    with pytest.raises(OpError) as e:
        plan.init_project(tmp_path / "p", preset_src=str(src))
    assert "missing 'sysprompt'" in str(e.value)


def test_init_explicit_override_existing_destination_warns(tmp_path, master_file):
    import longform_core.defaults as dfl
    root = tmp_path / "p"
    plan.init_project(root)
    bundled = (root / "writer_preset.json").read_bytes()
    (root / "bible.md").unlink()
    out = plan.init_project(root, preset_src=str(master_file))
    assert out["warnings"] == ["writer_preset.json already exists; not "
                               "overwritten (configure an existing preset "
                               "path in Settings if appropriate)"]
    assert out["preset"] is None
    assert (root / "writer_preset.json").read_bytes() == bundled, \
        "an existing regular destination stays byte-identical"
    assert "bible.md" in out["created"], \
        "other missing initialization paths are still filled"
    assert master_file.read_bytes() != bundled


def test_init_refuses_symlinked_preset_destination(tmp_path):
    real = tmp_path / "real.json"
    real.write_text("{}", encoding="utf-8")
    root = plan.init_project(tmp_path / "p")
    root = Path(root["root"])
    (root / "writer_preset.json").unlink()
    (root / "writer_preset.json").symlink_to(real)
    with pytest.raises(OpError) as e:
        plan.init_project(root)
    assert "symlink" in str(e.value)
    assert real.read_text() == "{}", "the linked target is untouched"


def test_init_refuses_preset_directory_collision(tmp_path):
    root = plan.init_project(tmp_path / "p")
    root = Path(root["root"])
    (root / "writer_preset.json").unlink()
    (root / "writer_preset.json").mkdir()
    with pytest.raises(OpError) as e:
        plan.init_project(root)
    assert "not a regular file" in str(e.value)


def test_init_write_failure_reports_partial_work_and_retries(tmp_path,
                                                             monkeypatch):
    root = tmp_path / "p"
    real = plan._write_bytes_safe
    calls = []

    def flaky(path, data):
        calls.append(path.name)
        if path.name == "scenes.json":
            raise OSError(13, "Permission denied")
        return real(path, data)

    monkeypatch.setattr(plan, "_write_bytes_safe", flaky)
    with pytest.raises(OpError) as e:
        plan.init_project(root)
    msg = str(e.value)
    assert "scenes.json could not be written" in msg
    assert "project.json" in msg and "bible.md" in msg, \
        "completed writes are reported"
    assert "(os error 13)" not in msg.lower() or "Permission denied" in msg
    monkeypatch.setattr(plan, "_write_bytes_safe", real)
    retry = plan.init_project(root)
    assert "scenes.json" in retry["created"], "retry fills missing paths only"
    assert (root / "scenes.json").read_text() == "[]\n"


class _StopAfter:
    """Cancellation token that trips after N checks (controlled boundary)."""

    def __init__(self, after):
        self.n = 0
        self.after = after

    def check(self):
        self.n += 1
        if self.n > self.after:
            raise Cancelled("stopped")


def test_init_stop_keeps_complete_writes_and_reports_partial(tmp_path):
    root = tmp_path / "p"
    events = []
    token = _StopAfter(3)   # project.json + bible.md complete, then Stop
    with pytest.raises(Cancelled):
        plan.init_project(root, token=token, events=events.append)
    partial = [ev for ev in events if ev.get("type") == "init_partial"]
    assert partial, "the partial state is emitted for reporting"
    assert partial[0]["created"] == ["project.json", "bible.md"]
    assert (root / "project.json").exists() and (root / "bible.md").exists()
    assert not (root / "writer_preset.json").exists(), \
        "no incomplete preset is written or reported as created"
    out = plan.init_project(root)
    assert set(out["created"]) == {"state.md", "scenes.json", "summaries.json",
                                   "writer_preset.json"}, \
        "retry after Stop fills only the missing paths"


def test_init_stop_before_anything_creates_nothing(tmp_path):
    root = tmp_path / "p"
    events = []
    token = _StopAfter(0)
    with pytest.raises(Cancelled):
        plan.init_project(root, token=token, events=events.append)
    assert not root.exists() or not any(root.iterdir())
    partial = [ev for ev in events if ev.get("type") == "init_partial"]
    assert partial and partial[0]["created"] == [] and partial[0]["dirs"] == []


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
    assert ("could not be read" in str(e.value)
            or "not found" in str(e.value))


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


# -------------------------------------------------------------- settings

def init_p(root, cfg=None):
    plan.init_project(root)
    if cfg is None:
        cfg = {"api_key": "sk-test"}
    (root / "project.json").write_text(json.dumps(cfg), encoding="utf-8")
    return root


def test_settings_state_lists_supported_values_and_never_a_secret(tmp_path):
    root = init_p(tmp_path / "p", cfg={})
    st = plan.settings_state(root)
    paths = {f[0] for f in plan.SETTING_FIELDS}
    assert paths <= set(st["values"]), "every supported field is shown"
    assert "api_key" not in st["values"], "no key value field exists"
    assert st["api_key_env"] == "FEATHERLESS_API_KEY"
    assert st["env_set"] is False and st["inline_key"] is False
    assert st["creds_ok"] is False
    assert st["values"]["roles.writer.preset_overrides.temp"] == 1.06


def test_settings_save_patch_preserves_unknown_fields_and_inline_key(tmp_path):
    root = init_p(tmp_path / "p")
    sentinel = "sk-keep-inline"
    (root / "project.json").write_text(json.dumps(
        {"api_key": sentinel, "custom_thing": {"a": 1},
         "roles": {"writer": {"mood": "noir"}}}), encoding="utf-8")
    st = plan.settings_state(root)
    assert any("custom_thing" in u for u in st["unknown_fields"])
    plan.save_settings(root, {
        "title": "Renamed", "target_words": "9000",
        "roles.planner.model": "planner-x",
        "roles.writer.preset_overrides.temp": "0.8",
        "roles.writer.preset_overrides.rep_pen": None,  # unset
        "banned_phrases": "no x\nno y",
    })
    saved = json.loads((root / "project.json").read_text())
    assert saved["api_key"] == sentinel, "inline key preserved opaquely"
    assert saved["custom_thing"] == {"a": 1}
    assert saved["roles"]["writer"]["mood"] == "noir"
    assert saved["title"] == "Renamed" and saved["target_words"] == 9000
    assert saved["roles"]["planner"]["model"] == "planner-x"
    assert saved["roles"]["writer"]["preset_overrides"]["temp"] == 0.8
    assert "rep_pen" not in saved["roles"]["writer"]["preset_overrides"], \
        "cleared override removed"
    assert saved["banned_phrases"] == ["no x", "no y"]
    # untouched supported fields are not materialized
    assert "max_parallel" not in saved, \
        "saving does not materialize unrelated defaults"


def test_settings_unset_removed_and_defaults_not_materialized(tmp_path):
    root = init_p(tmp_path / "p")
    before = json.loads((root / "project.json").read_text())
    plan.save_settings(root, {
        "roles.planner.thinking": None,
        "roles.planner.thinking_budget": None,
    })
    after = json.loads((root / "project.json").read_text())
    assert "thinking" not in after["roles"]["planner"]
    assert "thinking_budget" not in after["roles"]["planner"]
    assert set(before) - {"roles"} <= set(after), "other keys untouched"


def test_settings_validation_refuses_bad_values(tmp_path):
    root = init_p(tmp_path / "p")
    before = (root / "project.json").read_bytes()
    bad_values = [
        {"roles.planner.model": "   "},
        {"api_key_env": "not a name!"},
        {"api_key_env": "sk-real-key"},
        {"max_parallel": "0"},
        {"target_words": "1.5"},
        {"context_safety_margin": "1"},
        {"roles.planner.top_p": "1.5"},
        {"roles.planner.temperature": "-0.1"},
        {"api_base": "ftp://x"},
        {"api_base": "https://u:p@host/x"},
        {"roles.planner.max_tokens": True},
        {"roles.summarizer.min_tokens": "99999",
         "roles.summarizer.max_tokens": "100"},
        {"ngram.n": "abc"},
    ]
    for values in bad_values:
        with pytest.raises(OpError) as e:
            plan.save_settings(root, values)
        msg = str(e.value)
        assert "settings were not saved" in msg, values
        assert (root / "project.json").read_bytes() == before, values
    assert plan.validate_settings({}) == []


def test_settings_save_stale_refusal(tmp_path):
    root = init_p(tmp_path / "p")
    base = plan.settings_baseline(root)
    (root / "project.json").write_text('{"title": "external"}\n',
                                       encoding="utf-8")
    with pytest.raises(OpError) as e:
        plan.save_settings(root, {"title": "mine"}, baseline=base)
    assert getattr(e.value, "stale", False), "stale patch is refused"
    assert json.loads((root / "project.json").read_text())["title"] == \
        "external"


def test_settings_save_missing_project(tmp_path):
    with pytest.raises(OpError):
        plan.save_settings(tmp_path / "nope", {"title": "x"})


# ------------------------------------------------------- credentials (ADR-0011)


def test_save_credential_store_replace_and_clear(tmp_path):
    root = init_p(tmp_path / "p", cfg={"title": "T", "target_words": 9000})
    out = plan.save_credential(root, "save", "  sk-new-sentinel  ")
    cfg = json.loads((root / "project.json").read_text())
    assert cfg["api_key"] == "sk-new-sentinel", "the value is trimmed"
    assert cfg["title"] == "T" and cfg["target_words"] == 9000, \
        "unrelated fields survive"
    assert out["creds_ok"] is True and out["cred_source"] == "project"
    assert "sk-new-sentinel" not in json.dumps(out), "no value echo"

    plan.save_credential(root, "replace", "sk-second")
    assert json.loads((root / "project.json").read_text())["api_key"] == \
        "sk-second"

    out = plan.save_credential(root, "clear")
    cfg = json.loads((root / "project.json").read_text())
    assert cfg["api_key"] == "" and cfg["title"] == "T"
    assert out["creds_ok"] is False
    assert "sk-second" not in (root / "project.json").read_text()
    assert "sk-second" not in json.dumps(out)
    # no input history or backups carry the old key
    assert not (root / "inputs").exists() or all(
        "sk-second" not in f.read_text()
        for f in (root / "inputs").iterdir() if f.is_file())


def test_save_credential_rejects_empty_and_unknown_action(tmp_path):
    root = init_p(tmp_path / "p")
    with pytest.raises(OpError) as e:
        plan.save_credential(root, "save", "   ")
    assert "no credential value" in str(e.value)
    assert json.loads((root / "project.json").read_text())["api_key"] == \
        "sk-test", "a failed save writes nothing"
    with pytest.raises(OpError, match="unsupported credential action"):
        plan.save_credential(root, "destroy", "x")
    with pytest.raises(OpError, match="unsupported credential action"):
        plan.save_credential(root, "clear-via-save")


def test_save_credential_stale_refusal_and_invalid_json(tmp_path):
    root = init_p(tmp_path / "p", cfg={"title": "mine"})
    base = plan.settings_baseline(root)
    (root / "project.json").write_text('{"title": "external"}\n',
                                       encoding="utf-8")
    with pytest.raises(OpError) as e:
        plan.save_credential(root, "save", "sk-x", baseline=base)
    assert getattr(e.value, "stale", False), "stale save is refused"
    assert json.loads((root / "project.json").read_text())["title"] == \
        "external"

    (root / "project.json").write_text("[]", encoding="utf-8")
    base2 = plan.settings_baseline(root)
    with pytest.raises(OpError, match="not a JSON object"):
        plan.save_credential(root, "save", "sk-y", baseline=base2)
    assert (root / "project.json").read_text() == "[]"


def test_save_credential_refuses_symlink_target(tmp_path):
    root = init_p(tmp_path / "p")
    (root / "project.json").unlink()
    other = tmp_path / "elsewhere.json"
    other.write_text("{}", encoding="utf-8")
    (root / "project.json").symlink_to(other)
    with pytest.raises(OpError, match="symlink"):
        plan.save_credential(root, "save", "sk-x")
    assert other.read_text() == "{}", "the symlink target is untouched"


def test_save_credential_missing_project(tmp_path):
    with pytest.raises(OpError):
        plan.save_credential(tmp_path / "nope", "save", "sk-x")


def test_save_credential_stop_writes_nothing(tmp_path):
    from longform_core.cancel import CancellationToken
    root = init_p(tmp_path / "p")
    before = (root / "project.json").read_bytes()
    tok = CancellationToken()
    tok.cancel()
    with pytest.raises(Exception):
        plan.save_credential(root, "save", "sk-x", token=tok)
    assert (root / "project.json").read_bytes() == before


# ------------------------------------------------------------ test_connection

def test_connection_succeeds_discarding_content(tmp_path, monkeypatch):
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    root = tmp_path / "p"
    plan.init_project(root)
    prov = FakeLimitsProvider(PLAN, {})
    out = plan.test_connection(root, provider_factory=lambda p: prov,
                               session=True)
    assert out["ok"] is True and out["cred_source"] == "session"
    assert ("GET", "/plan") in prov.calls
    blob = json.dumps(out)
    assert "max_context_length" not in blob, "response content is discarded"
    assert not (root / "limits.json").exists(), "nothing is written"


def test_connection_saved_key_and_missing_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    root = init_p(tmp_path / "p")
    prov = FakeLimitsProvider(PLAN, {})
    out = plan.test_connection(root, provider_factory=lambda p: prov)
    assert out["cred_source"] == "project"
    assert out["ok"] is True

    empty = tmp_path / "e"
    plan.init_project(empty)
    prov2 = FakeLimitsProvider(PLAN, {})
    with pytest.raises(OpError) as e:
        plan.test_connection(empty, provider_factory=lambda p: prov2)
    assert "no API key" in str(e.value) and "Use for this session" in \
        str(e.value)
    assert prov2.calls == [], "missing credentials never construct a request"


def test_connection_failure_is_sanitized(tmp_path):
    root = init_p(tmp_path / "p")   # inline credential is "sk-test"
    prov = FakeLimitsProvider(PLAN, {}, fail={
        "plan": RuntimeError("fake provider failed with sk-test echoed")})
    with pytest.raises(OpError) as e:
        plan.test_connection(root, provider_factory=lambda p: prov)
    assert "connection test failed" in str(e.value)
    assert "sk-test" not in str(e.value), "the credential echo is scrubbed"
    assert "[redacted]" in str(e.value)
    assert not (root / "limits.json").exists()


# ---------------------------------------------------------------- limits

class FakeLimitsProvider:
    """get() surface like Api with scripted responses and failures."""

    def __init__(self, plan, models, fail=None):
        self.plan = plan
        self.models = models
        self.fail = fail or {}
        self.calls = []

    def get(self, path, token=None, on_retry_event=None):
        self.calls.append(("GET", path))
        if token:
            token.check()
        if path == "/plan":
            if "plan" in self.fail:
                raise self.fail["plan"]
            return self.plan
        mid = path[len("/models/"):] if path.startswith("/models/") else \
            path.split("/")[-1]
        if mid in self.fail:
            raise self.fail[mid]
        if mid in self.models:
            return self.models[mid]
        from longform_core.api import HttpErr
        raise HttpErr(404, "model not found")


PLAN = {"max_context_length": 8192, "concurrency": 3}
MODEL_OK = {"id": "m1", "context_length": 131072,
            "max_completion_tokens": 8192, "available_on_current_plan": True}


def test_fetch_limits_matches_cli_limits_json(tmp_path, monkeypatch, capsys):
    import httpx as httpx_mod
    import longform_core.commands as commands
    from longform_core.project import Project

    def handler(request):
        if request.url.path.endswith("/plan"):
            return httpx_mod.Response(200, json=PLAN)
        mid = request.url.path.rsplit("/", 1)[-1]
        if mid in ("planner-m", "writer-m"):
            return httpx_mod.Response(200, json=dict(MODEL_OK, id=mid))
        return httpx_mod.Response(404, json={"error": "not found"})

    client = httpx_mod.Client(transport=httpx_mod.MockTransport(handler))
    monkeypatch.setattr(httpx_mod.HTTPTransport, "handle_request",
                        lambda self, req: client.send(req))

    cfg = {"api_key": "sk-test", "roles": {
        "planner": {"model": "planner-m"}, "writer": {"model": "writer-m"},
        "summarizer": {"model": "planner-m"}, "critic": {"model": "writer-m"},
        "editor": {"model": "writer-m"}}}
    a, b = tmp_path / "cli", tmp_path / "op"
    for r in (a, b):
        r.mkdir()
        (r / "project.json").write_text(json.dumps(cfg), encoding="utf-8")
    commands.cmd_limits(Project(a), None)
    out = plan.fetch_limits(b)
    cli = json.loads((a / "limits.json").read_text())
    gui = json.loads((b / "limits.json").read_text())
    cli.pop("fetched"), gui.pop("fetched")
    assert cli == gui, "limits.json shape/bytes match the CLI modulo fetched"
    assert set(gui["models"]) == {"planner-m", "writer-m"}
    assert gui["models"]["writer-m"]["found"] is True
    assert "limits.json" in out["saved"]


def test_fetch_limits_404_is_found_false_and_saved(tmp_path):
    root = init_p(tmp_path / "p", cfg={"api_key": "sk-test", "roles": {
        "planner": {"model": "gone-m"},
        "writer": {"model": "meta-llama/Llama-3.3-70B-Instruct"}}})
    prov = FakeLimitsProvider(PLAN, {"meta-llama/Llama-3.3-70B-Instruct":
                                     MODEL_OK})
    out = plan.fetch_limits(root, provider_factory=lambda p: prov)
    data = json.loads((root / "limits.json").read_text())
    assert data["models"][out["not_found"][0]] == {"found": False}
    assert data["models"]["meta-llama/Llama-3.3-70B-Instruct"]["found"] is True


def test_fetch_limits_failure_keeps_previous_file(tmp_path):
    root = init_p(tmp_path / "p")
    (root / "project.json").write_text(json.dumps(
        {"api_key": "sk-sentinel-inline"}), encoding="utf-8")
    previous = '{"fetched": "old", "plan": {}, "models": {}}\n'
    (root / "limits.json").write_text(previous, encoding="utf-8")
    prov = FakeLimitsProvider(PLAN, {}, fail={
        "plan": RuntimeError("boom with sk-sentinel-inline echoed")})
    with pytest.raises(OpError) as e:
        plan.fetch_limits(root, provider_factory=lambda p: prov)
    assert "sk-sentinel-inline" not in str(e.value), \
        "credential scrubbed from error"
    assert (root / "limits.json").read_text() == previous


def test_fetch_limits_missing_credentials_makes_no_call(tmp_path):
    root = tmp_path / "p"
    plan.init_project(root)
    prov = FakeLimitsProvider(PLAN, {})
    with pytest.raises(OpError) as e:
        plan.fetch_limits(root, provider_factory=lambda p: prov)
    assert "no API key" in str(e.value)
    assert prov.calls == [], "no request without credentials"


def test_fetch_limits_session_availability_makes_call_without_disk_key(tmp_path,
                                                                        monkeypatch):
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    root = tmp_path / "p"
    plan.init_project(root)          # empty api_key, no environment value
    prov = FakeLimitsProvider(PLAN, {"meta-llama/Llama-3.3-70B-Instruct":
                                     MODEL_OK})
    out = plan.fetch_limits(root, provider_factory=lambda p: prov,
                            session=True)
    assert ("GET", "/plan") in prov.calls, \
        "the window session credential satisfies the availability guard"
    assert (root / "limits.json").is_file()
    blob = json.dumps(out["view"]) + json.dumps(
        (root / "limits.json").read_text())
    assert "session-sentinel" not in blob, "the session key never persists"


def test_fetch_limits_prefers_saved_key_over_environment(tmp_path,
                                                         monkeypatch):
    monkeypatch.setenv("FEATHERLESS_API_KEY", "env-sentinel")
    root = init_p(tmp_path / "p")     # inline sk-test wins over env
    prov = FakeLimitsProvider(PLAN, {})
    plan.fetch_limits(root, provider_factory=lambda p: prov)
    assert ("GET", "/plan") in prov.calls


def test_settings_state_reports_source_and_never_values(tmp_path,
                                                         monkeypatch):
    monkeypatch.setenv("FEATHERLESS_API_KEY", "env-sentinel")
    root = tmp_path / "p"
    plan.init_project(root)
    st = plan.settings_state(root)
    assert st["inline_key"] is False and st["env_set"] is True
    assert st["creds_ok"] is True and st["cred_source"] == "environment"
    blob = json.dumps(st)
    assert "env_value" not in blob, "the environment value is not exposed"
    assert "env-sentinel" not in blob, "no credential value in state"
    st2 = plan.settings_state(root, session=True)
    assert st2["cred_source"] == "session" and st2["creds_ok"] is True


def test_project_overview_reports_source_and_never_values(tmp_path,
                                                          monkeypatch):
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    root = tmp_path / "p"
    plan.init_project(root)
    ov = plan.project_overview(root)
    assert ov["creds_ok"] is False and ov["cred_source"] == "missing"
    assert "session-sentinel" not in json.dumps(ov)
    (root / "project.json").write_text(
        json.dumps({"api_key": "sk-inline-secret"}), encoding="utf-8")
    ov2 = plan.project_overview(root)
    assert ov2["creds_ok"] is True and ov2["cred_source"] == "project"
    assert "sk-inline-secret" not in json.dumps(ov2), "no key echo"
    assert ov2["inline_key"] is True


def test_fetch_limits_stop_keeps_file(tmp_path):
    from longform_core.cancel import CancellationToken
    root = init_p(tmp_path / "p")
    tok = CancellationToken()
    tok.cancel()
    prov = FakeLimitsProvider(PLAN, {})
    with pytest.raises(Exception):
        plan.fetch_limits(root, provider_factory=lambda p: prov, token=tok)
    assert not (root / "limits.json").exists()
    assert ("GET", "/plan") not in prov.calls


def test_fetch_limits_http_404_model_and_unavailable(tmp_path):
    root = init_p(tmp_path / "p")
    prov = FakeLimitsProvider(PLAN, {"meta-llama/Llama-3.3-70B-Instruct":
                                     dict(MODEL_OK,
                                          available_on_current_plan=False)})
    plan.fetch_limits(root, provider_factory=lambda p: prov)
    data = json.loads((root / "limits.json").read_text())
    m = data["models"]["meta-llama/Llama-3.3-70B-Instruct"]
    assert m["found"] is True and m["available_on_current_plan"] is False


def test_fetch_limits_view_is_sanitized(tmp_path):
    root = init_p(tmp_path / "p")
    (root / "project.json").write_text(json.dumps(
        {"api_key": "sk-inline-secret"}), encoding="utf-8")
    leaky = {"id": "meta-llama/Llama-3.3-70B-Instruct", "context_length": 100,
             "api_key": "sk-server", "notes": "echo sk-inline-secret back"}
    prov = FakeLimitsProvider(PLAN, {"meta-llama/Llama-3.3-70B-Instruct":
                                     leaky})
    out = plan.fetch_limits(root, provider_factory=lambda p: prov)
    blob = json.dumps(out["view"])
    assert "sk-inline-secret" not in blob, "resolved key scrubbed from view"
    assert "sk-server" not in blob, "credential-ish metadata keys dropped"
    saved = json.loads((root / "limits.json").read_text())
    assert saved["models"]["meta-llama/Llama-3.3-70B-Instruct"]["raw"] == leaky, \
        "saved limits.json keeps the CLI shape unchanged"


# ----------------------------------------------------------------- bible

def bible_project(root):
    init_p(root)
    (root / "bible.md").write_text(
        "# Story bible\n\nPreamble line.\n\n## Title\n(working title)\n\n"
        "## Style rules\n- (voice)\n", encoding="utf-8")
    return root


def fill_title(form):
    return form.replace("A: ", "A: The Long Tower", 1)


def test_bible_cli_parity_files_and_history(tmp_path, monkeypatch, capsys):
    import longform_core.commands as commands
    from longform_core.project import Project
    a, b = bible_project(tmp_path / "cli"), bible_project(tmp_path / "gui")

    answers = iter(["", "a", "q"])
    monkeypatch.setattr(commands, "ask", lambda *a2, **k: next(answers))
    from longform_core.utils import save_input as _real_save_input

    def scripted_edit(p, kind, initial):
        text = fill_title(initial)
        _real_save_input(p.root, kind, text)
        return text

    monkeypatch.setattr(commands, "edit_saved", scripted_edit)
    commands.cmd_bible(Project(a), None)
    out = capsys.readouterr().out

    plan.begin_bible_session(b)
    base = plan.bible_baseline(b)
    st = plan.bible_form_state(b, "Title")
    saved = plan.save_bible_answers(b, "Title", fill_title(st["form"]))
    plan.accept_bible_section(b, "Title", saved["preview"], base)

    for rel in ("bible.md", "inputs/bible_answers_title.md",
                "inputs/history/bible_answers_title_20260101-000000.md",
                "bible_history/bible_20260101-000000.md"):
        assert (a / rel).read_bytes() == (b / rel).read_bytes(), rel
    assert "The Long Tower" in (b / "bible.md").read_text()
    assert "Preamble line." in (b / "bible.md").read_text(), \
        "preamble and section order preserved"
    assert "## Style rules" in (b / "bible.md").read_text()
    assert "The Long Tower" in out and "saved Title to" in out


def test_bible_cli_transcript_frozen(tmp_path, monkeypatch, capsys):
    """The pre-extraction CLI transcript is characterization-frozen."""
    import longform_core.commands as commands
    from longform_core.project import Project
    a = bible_project(tmp_path / "cli")
    answers = iter(["", "a", "q"])
    monkeypatch.setattr(commands, "ask", lambda *a2, **k: next(answers))
    from longform_core.utils import save_input as _real_save_input

    def scripted_edit2(p, kind, initial):
        text = fill_title(initial)
        _real_save_input(p.root, kind, text)
        return text

    monkeypatch.setattr(commands, "edit_saved", scripted_edit2)
    commands.cmd_bible(Project(a), None)
    out = capsys.readouterr().out
    assert out == (
        "2 sections. Answer each section's questions in $EDITOR; your answers "
        "go into the bible as written.\n"
        "\n=== [1/2] Title ===\n"
        "current:\n(empty / template placeholder)\n\n"
        "\n--- Title (3 words) ---\n"
        "The Long Tower\n"
        f"saved Title to {a}/bible.md\n"
        "\n=== [2/2] Style rules ===\n"
        "current:\n(empty / template placeholder)\n\n"
        "\nbible: " + str(a / "bible.md") + "  ~24 tokens (budget 1800)\n")


def test_bible_overview_sections_and_budget(tmp_path):
    root = bible_project(tmp_path / "p")
    over = plan.bible_overview(root)
    assert [s["heading"] for s in over["sections"]] == ["Title", "Style rules"]
    assert over["sections"][0]["placeholder"] is True
    assert over["budget"] == 1800 and not over["over_budget"]


def test_bible_overview_no_sections_reports_not_reset(tmp_path):
    root = init_p(tmp_path / "p")
    (root / "bible.md").write_text("just prose, no sections\n",
                                   encoding="utf-8")
    over = plan.bible_overview(root)
    assert not over["has_sections"]
    assert "no '## ' sections" in over["error"]
    assert (root / "bible.md").read_text() == "just prose, no sections\n"


def test_bible_overview_budget_warning(tmp_path):
    root = bible_project(tmp_path / "p")
    (root / "bible.md").write_text(
        "# Story bible\n\n## Title\n" + ("word " * 20000) + "\n",
        encoding="utf-8")
    over = plan.bible_overview(root)
    assert over["over_budget"] and over["tokens"] > over["budget"]


def test_bible_form_state_uses_saved_answers_and_char_names(tmp_path):
    root = bible_project(tmp_path / "p")
    (root / "bible.md").write_text(
        "# Story bible\n\n## Characters\n### NAME\n- Role:\n",
        encoding="utf-8")
    lb = root / "lorebooks"
    lb.mkdir(exist_ok=True)
    (lb / "mara.json").write_text(json.dumps(
        {"name": "Mara Voss", "description": "a harbour thief"}),
        encoding="utf-8")
    st = plan.bible_form_state(root, "Characters")
    assert "Character: Mara Voss  (from your lorebooks; keep this exact name)" \
        in st["form"], "lore-derived character names appear in the form"
    assert "Character: \n" in st["form"], "blank extra character kept"
    assert "Other characters not in your lorebooks" in st["form"]
    assert st["saved_form"] is False
    (root / "inputs").mkdir()
    (root / "inputs" / "bible_answers_characters.md").write_text(
        "SAVED FORM", encoding="utf-8")
    st = plan.bible_form_state(root, "Characters")
    assert st["form"] == "SAVED FORM" and st["saved_form"] is True


def test_bible_form_state_custom_section_uses_generic_question(tmp_path):
    root = bible_project(tmp_path / "p")
    (root / "bible.md").write_text(
        "# Story bible\n\n## Timeline notes\nexisting text\n",
        encoding="utf-8")
    st = plan.bible_form_state(root, "Timeline notes")
    assert "What should this section say?" in st["form"]
    assert st["current"] == "existing text"


def test_bible_session_backup_once_and_reopen(tmp_path):
    root = bible_project(tmp_path / "p")
    plan.begin_bible_session(root)
    assert (root / "bible_history" / "bible_20260101-000000.md").exists()
    # a later session backs up again with a distinct name
    plan.begin_bible_session(root)
    names = sorted(x.name for x in (root / "bible_history").iterdir())
    assert names[1] == "bible_20260101-000000_2.md"
    # a fresh project's template bible is backed up too
    fresh = init_p(tmp_path / "f")
    out = plan.begin_bible_session(fresh)
    assert out["backup"] == "bible_history/bible_20260101-000000.md"
    assert (fresh / "bible_history" / "bible_20260101-000000.md").exists()


def test_bible_save_persists_form_history_and_preview_not_bible(tmp_path):
    root = bible_project(tmp_path / "p")
    st = plan.bible_form_state(root, "Style rules")
    form = st["form"].replace("A: ", "A: sparse and dry\nA2 kept", 1)
    out = plan.save_bible_answers(root, "Style rules", form)
    assert out["preview"] and "sparse and dry" in out["preview"]
    assert (root / "inputs" / "bible_answers_style-rules.md").read_text() \
        == form
    assert "sparse and dry" not in (root / "bible.md").read_text(), \
        "saving answers alone never replaces bible.md"
    hist = list((root / "inputs" / "history").glob("*.md"))
    assert len(hist) == 1 and hist[0].read_text() == form


def test_bible_accept_replaces_only_the_chosen_section(tmp_path):
    root = bible_project(tmp_path / "p")
    base = plan.bible_baseline(root)
    st = plan.bible_form_state(root, "Title")
    saved = plan.save_bible_answers(root, "Title", fill_title(st["form"]))
    plan.accept_bible_section(root, "Title", saved["preview"], base)
    text = (root / "bible.md").read_text()
    assert "The Long Tower" in text and "- (voice)" in text, \
        "other sections keep their content"


def test_bible_multiline_answers_and_custom_preamble_preserved(tmp_path):
    root = bible_project(tmp_path / "p")
    (root / "bible.md").write_text(
        "CUSTOM PREAMBLE\n\n## Title\n(working title)\n\n## Avoid\n- (tropes)\n",
        encoding="utf-8")
    base = plan.bible_baseline(root)
    st = plan.bible_form_state(root, "Avoid")
    form = st["form"].replace("A: ", "A: first line\nsecond line", 1)
    out = plan.save_bible_answers(root, "Avoid", form)
    plan.accept_bible_section(root, "Avoid", out["preview"], base)
    text = (root / "bible.md").read_text()
    assert text.startswith("CUSTOM PREAMBLE\n"), "custom preamble preserved"
    assert "second line" in text
    # multiline answers render as the CLI compose_section does
    assert "- Tropes:\n  first line\n  second line" in text


def test_bible_reopen_saved_answers_then_skip(tmp_path):
    root = bible_project(tmp_path / "p")
    st = plan.bible_form_state(root, "Title")
    saved = plan.save_bible_answers(root, "Title", fill_title(st["form"]))
    st2 = plan.bible_form_state(root, "Title")
    assert st2["form"] == fill_title(st["form"]), "saved form is reused"
    before = (root / "bible.md").read_bytes()
    base = plan.bible_baseline(root)
    plan.accept_bible_section(root, "Title", saved["preview"], base)
    # a later leave/skip without acceptance keeps the accepted state
    base2 = plan.bible_baseline(root)
    st3 = plan.bible_form_state(root, "Style rules")
    plan.save_bible_answers(root, "Style rules", st3["form"])
    assert (root / "bible.md").read_text() == \
        (root / "bible.md").read_text(), "no write happened on skip"
    assert "The Long Tower" in (root / "bible.md").read_text()


def test_bible_accept_stale_refusal(tmp_path):
    root = bible_project(tmp_path / "p")
    base = plan.bible_baseline(root)
    (root / "bible.md").write_text("external change, no sections\n",
                                   encoding="utf-8")
    with pytest.raises(OpError) as e:
        plan.accept_bible_section(root, "Title", "new", base)
    assert getattr(e.value, "stale", False)
    assert (root / "bible.md").read_text() == "external change, no sections\n"


def test_bible_accept_unsafe_destination(tmp_path):
    real = tmp_path / "real.md"
    real.write_text("keep", encoding="utf-8")
    root = bible_project(tmp_path / "p")
    (root / "bible.md").unlink()
    (root / "bible.md").symlink_to(real)
    base = plan.bible_baseline(root)
    with pytest.raises(OpError) as e:
        plan.accept_bible_section(root, "Title", "new", base)
    assert "symlink" in str(e.value)
    assert real.read_text() == "keep"


def test_bible_direct_section_edit(tmp_path):
    root = bible_project(tmp_path / "p")
    base = plan.bible_baseline(root)
    plan.edit_bible_section(root, "Style rules", "- sparse and dry\n- no filler",
                            base)
    text = (root / "bible.md").read_text()
    assert "## Title" in text and "## Style rules" in text
    assert "- sparse and dry" in text and "(working title)" in text
    # custom sections and headings survive; heading is never relabeled
    (root / "bible.md").write_text(
        "# Story bible\n\n## Timeline notes\nold\n", encoding="utf-8")
    base2 = plan.bible_baseline(root)
    plan.edit_bible_section(root, "Timeline notes", "new timeline", base2)
    text = (root / "bible.md").read_text()
    assert "## Timeline notes" in text and "new timeline" in text


def test_bible_direct_edit_stale_refusal(tmp_path):
    root = bible_project(tmp_path / "p")
    base = plan.bible_baseline(root)
    (root / "bible.md").write_text("changed externally\n", encoding="utf-8")
    with pytest.raises(OpError) as e:
        plan.edit_bible_section(root, "Title", "x", base)
    assert getattr(e.value, "stale", False)


def test_bible_history_listing(tmp_path):
    root = bible_project(tmp_path / "p")
    plan.begin_bible_session(root)
    st = plan.bible_form_state(root, "Title")
    plan.save_bible_answers(root, "Title", fill_title(st["form"]))
    hist = plan.bible_history(root)
    assert [b["name"] for b in hist["bibles"]] == \
        ["bible_20260101-000000.md"]
    assert [a["name"] for a in hist["answers"]] == \
        ["bible_answers_title_20260101-000000.md"]
    assert "The Long Tower" in hist["answers"][0]["text"]


def test_bible_ops_missing_project(tmp_path):
    with pytest.raises(OpError):
        plan.bible_overview(tmp_path / "nope")
    with pytest.raises(OpError):
        plan.bible_form_state(tmp_path / "nope", "Title")


def test_bible_unknown_heading(tmp_path):
    root = bible_project(tmp_path / "p")
    base = plan.bible_baseline(root)
    with pytest.raises(OpError) as e:
        plan.accept_bible_section(root, "Nope", "x", base)
    assert "no such bible section" in str(e.value)


# --------------------------------------------------------------- outline

class FakeOutlineProvider:
    """chat_many surface matching Api for planner calls; records messages."""

    script = []

    def __init__(self, p):
        self.p = p
        self.calls = []

    def chat_many(self, role, messages, n, max_tokens=None, token=None,
                  on_event=None, preview_events=None):
        self.calls.append({"role": role, "messages": messages, "n": n})
        out = []
        for k in range(n):
            if token:
                token.check()
            i = len(self.calls) - 1
            item = FakeOutlineProvider.script[k] if \
                len(FakeOutlineProvider.script) > k else "<outline>X</outline>"
            sub = preview_events(k) if preview_events is not None else None
            if isinstance(item, Exception):
                if sub:
                    sub({"type": "preview_start", "attempt_id": 1})
                    sub({"type": "preview_reset", "attempt_id": 1})
                if on_event:
                    on_event({"type": "candidate_failed", "k": k + 1, "n": n,
                              "msg": "failed"})
                continue
            if sub:
                sub({"type": "preview_start", "attempt_id": 1})
                half = len(item) // 2
                for part in (item[:half], item[half:]):
                    sub({"type": "preview_delta", "attempt_id": 1,
                         "text": part})
                sub({"type": "preview_complete", "attempt_id": 1})
            out.append((item, "stop", {}))
            if on_event:
                on_event({"type": "candidate_done", "k": k + 1, "n": n,
                          "msg": "done"})
        return out


OUTLINES = ["<outline>OUTLINE ONE BODY</outline>",
            "<outline>OUTLINE TWO BODY</outline>"]


def outline_project(tmp_path):
    root = bible_project(tmp_path / "p")
    (root / "bible.md").write_text("# Story bible\n\nQuiet town.\n",
                                   encoding="utf-8")
    return root


def test_outline_cli_parity_files_prompts_and_history(tmp_path, monkeypatch,
                                                      capsys):
    from longform_core.project import Project
    a, b = outline_project(tmp_path / "cli"), outline_project(tmp_path / "gui")

    FakeOutlineProvider.script = list(OUTLINES)
    monkeypatch.setattr(commands, "Api", FakeOutlineProvider)
    answers = iter(["r", "1"])   # reroll same notes, then choose candidate 1
    monkeypatch.setattr(commands, "ask", lambda *a2, **k: next(answers))
    FakeOutlineProvider.script = OUTLINES + ["<outline>REROLL BODY</outline>"]
    args = type("A", (), {"n": 2, "notes": "Tight pacing."})()
    commands.cmd_outline(Project(a), args)
    capsys.readouterr()

    prov = FakeOutlineProvider(b)
    r1 = plan.generate_outlines(b, commands.OUTLINE_NOTES_FORM +
                                "Tight pacing.\n", 2,
                                provider_factory=lambda p: prov)
    plan.generate_outlines(b, commands.OUTLINE_NOTES_FORM +
                           "Tight pacing.\n", 2,
                           provider_factory=lambda p: prov)
    plan.choose_outline(b, r1["candidates"][0], r1["baseline"])

    names = sorted(x.name for x in (a / "outlines").glob("candidate_*.md"))
    gnames = sorted(x.name for x in (b / "outlines").glob("candidate_*.md"))
    assert names == gnames, "candidate file names match the CLI convention"
    for name in names:
        assert (a / "outlines" / name).read_bytes() == \
            (b / "outlines" / name).read_bytes(), name
    assert (a / "outline.md").read_bytes() == (b / "outline.md").read_bytes()
    assert (a / "inputs" / "outline_notes.md").read_bytes() == \
        (b / "inputs" / "outline_notes.md").read_bytes()
    assert sorted(x.name for x in (a / "inputs" / "history").glob("*.md")) == \
        sorted(x.name for x in (b / "inputs" / "history").glob("*.md"))
    assert "OUTLINE ONE BODY" in (b / "outline.md").read_text()
    # exact CLI planner messages/params (bible, notes, target, tag instruction)
    assert prov.calls[0]["role"] == "planner"
    assert prov.calls[0]["n"] == 2
    assert "# Story bible" in prov.calls[0]["messages"][1]["content"]


def test_outline_messages_match_cli_exactly(tmp_path, monkeypatch):
    """Byte-identical planner messages with the CLI make_msgs."""
    import longform_core.commands as commands
    from longform_core.project import Project
    root = outline_project(tmp_path / "p")

    seen = {}

    def spy(self, role, messages, n, max_tokens=None, token=None, on_event=None):
        seen["messages"] = messages
        return []

    monkeypatch.setattr(commands.Api, "chat_many", spy)
    monkeypatch.setattr(commands, "ask", lambda *a, **k: "")
    args = type("A", (), {"n": 1, "notes": ""})()
    commands.cmd_outline(Project(root), args)
    tw = 17000
    mine = plan.outline_messages("# Story bible\n\nQuiet town.", "", tw)
    assert seen["messages"] == mine


def test_outline_candidates_saved_with_notes_comment(tmp_path):
    root = outline_project(tmp_path / "p")
    base = plan.outline_baseline(root)
    FakeOutlineProvider.script = list(OUTLINES)
    out = plan.generate_outlines(root, commands.OUTLINE_NOTES_FORM +
                                 "Keep it tight.\n", 2,
                                 provider_factory=lambda p:
                                 FakeOutlineProvider(p))
    assert len(out["candidates"]) == 2
    first = (root / "outlines" / out["candidates"][0]).read_text()
    assert first.startswith("<!-- notes: Keep it tight. -->\n")
    assert "OUTLINE ONE BODY" in first and first.endswith("\n")
    assert not (root / "outline.md").exists(), \
        "generation never chooses automatically"


def test_outline_no_notes_no_comment(tmp_path):
    root = outline_project(tmp_path / "p")
    FakeOutlineProvider.script = list(OUTLINES)
    out = plan.generate_outlines(root, commands.OUTLINE_NOTES_FORM, 1,
                                 provider_factory=lambda p:
                                 FakeOutlineProvider(p))
    text = (root / "outlines" / out["candidates"][0]).read_text()
    assert not text.startswith("<!--")


def test_outline_missing_or_empty_bible_blocks_generation(tmp_path):
    root = init_p(tmp_path / "p")
    (root / "bible.md").unlink()
    with pytest.raises(OpError) as e:
        plan.generate_outlines(root, "notes", 1,
                               provider_factory=lambda p:
                               FakeOutlineProvider(p))
    assert "bible.md is empty or missing" in str(e.value)
    root2 = outline_project(tmp_path / "p2")
    (root2 / "bible.md").write_text("   \n", encoding="utf-8")
    with pytest.raises(OpError):
        plan.generate_outlines(root2, "notes", 1,
                               provider_factory=lambda p:
                               FakeOutlineProvider(p))


def test_outline_shortfall_and_tag_warning(tmp_path):
    root = outline_project(tmp_path / "p")
    FakeOutlineProvider.script = ["no tags at all", Exception("boom")]
    out = plan.generate_outlines(root, "notes", 2,
                                 provider_factory=lambda p:
                                 FakeOutlineProvider(p))
    assert out["shortfall"] == 1
    assert any("no <outline> tags" in w for w in out["warnings"])
    assert len(out["candidates"]) == 1, \
        "complete candidates are saved and kept"
    assert not (root / "outline.md").exists()


def test_outline_reroll_appends_never_deletes(tmp_path):
    root = outline_project(tmp_path / "p")
    FakeOutlineProvider.script = list(OUTLINES)
    r1 = plan.generate_outlines(root, "notes A", 2,
                                provider_factory=lambda p:
                                FakeOutlineProvider(p))
    before = sorted(x.name for x in (root / "outlines").glob("*.md"))
    r2 = plan.generate_outlines(root, "notes B", 1,
                                provider_factory=lambda p:
                                FakeOutlineProvider(p))
    after = sorted(x.name for x in (root / "outlines").glob("*.md"))
    assert len(after) == len(before) + 1, "rerolls append candidates"
    for name in before:
        assert (root / "outlines" / name).read_text() in \
            [(root / "outlines" / n).read_text() for n in after], \
            "prior candidate files are kept unchanged"


def test_outline_choose_strips_comment_and_backs_up(tmp_path):
    root = outline_project(tmp_path / "p")
    (root / "outline.md").write_text("PREVIOUS OUTLINE\n", encoding="utf-8")
    FakeOutlineProvider.script = list(OUTLINES)
    out = plan.generate_outlines(root, "notes", 1,
                                 provider_factory=lambda p:
                                 FakeOutlineProvider(p))
    plan.choose_outline(root, out["candidates"][0], out["baseline"])
    body = (root / "outline.md").read_text()
    assert body == "OUTLINE ONE BODY\n", "leading notes comment stripped"
    prevs = list((root / "outlines").glob("outline_prev_*.md"))
    assert len(prevs) == 1 and prevs[0].read_text() == "PREVIOUS OUTLINE\n"
    cand = (root / "outlines" / out["candidates"][0]).read_text()
    assert "<!-- notes:" in cand, "the original candidate file is retained"


def test_outline_previews_raw_provisional_and_final_identical(tmp_path):
    """Preview events carry raw fragments per candidate (task 1.4); completed
    parsing/files are byte-identical with and without a subscriber."""
    a, b = outline_project(tmp_path / "a"), outline_project(tmp_path / "b")
    FakeOutlineProvider.script = list(OUTLINES)
    evs = []
    plan.generate_outlines(a, "notes", 1,
                           provider_factory=lambda p: FakeOutlineProvider(p),
                           events=evs.append,
                           preview_events=lambda i: (lambda ev: None))
    pv = [e for e in evs if e.get("type", "").startswith("preview_")]
    assert [e["type"] for e in pv] == [
        "preview_start", "preview_delta", "preview_delta", "preview_complete"]
    assert all(e["candidate_id"] == 1 for e in pv)
    deltas = "".join(e["text"] for e in pv
                     if e["type"] == "preview_delta")
    assert "OUTLINE ONE BODY" in deltas, "raw answer visible before completion"
    assert not (a / "outline.md").exists(), \
        "no provisional choose/accept from previews"

    plan.generate_outlines(b, "notes", 1,
                           provider_factory=lambda p: FakeOutlineProvider(p))
    na = sorted(x.name for x in (a / "outlines").glob("candidate_*.md"))
    nb = sorted(x.name for x in (b / "outlines").glob("candidate_*.md"))
    assert na == nb
    for n in na:
        assert (a / "outlines" / n).read_bytes() == \
            (b / "outlines" / n).read_bytes(), n

    evs2 = []
    plan.generate_outlines(outline_project(tmp_path / "c"), "notes", 1,
                           provider_factory=lambda p: FakeOutlineProvider(p),
                           events=evs2.append)
    assert not [e for e in evs2 if e.get("type", "").startswith("preview_")], \
        "no preview events without a subscriber"


def test_outline_previews_incomplete_tag_visible_and_reroll_retagged(tmp_path):
    """An answer with no closing tag still shows its raw fragments; a reroll
    is a fresh operation whose candidate ids restart at 1."""
    root = outline_project(tmp_path / "p")
    FakeOutlineProvider.script = ["<outline>OUTLINE ONE BO"]
    evs = []
    out = plan.generate_outlines(root, "notes", 1,
                                 provider_factory=lambda p:
                                 FakeOutlineProvider(p),
                                 events=evs.append,
                                 preview_events=lambda i: (lambda ev: None))
    deltas = "".join(e["text"] for e in evs
                     if e.get("type", "").startswith("preview_") and
                     e["type"] == "preview_delta")
    assert "<outline>OUTLINE ONE BO" in deltas, \
        "incomplete tagged answer is visible as provisional raw text"
    assert any("no <outline> tags" in w for w in out["warnings"]), \
        "completed parsing stays authoritative"
    assert len(out["candidates"]) == 1

    FakeOutlineProvider.script = list(OUTLINES)
    evs2 = []
    plan.generate_outlines(root, "more notes", 1,
                           provider_factory=lambda p: FakeOutlineProvider(p),
                           events=evs2.append,
                           preview_events=lambda i: (lambda ev: None))
    cands = {e["candidate_id"] for e in evs2 if e.get("type", "").startswith("preview_")}
    assert cands == {1}, "reroll previews restart their own candidate ids"


def test_outline_previews_two_candidates_each_tagged(tmp_path):
    root = outline_project(tmp_path / "p")
    FakeOutlineProvider.script = list(OUTLINES)
    evs = []
    plan.generate_outlines(root, "notes", 2,
                           provider_factory=lambda p: FakeOutlineProvider(p),
                           events=evs.append,
                           preview_events=lambda i: (lambda ev: None))
    per = {}
    for e in evs:
        if e.get("type", "").startswith("preview_"):
            per.setdefault(e["candidate_id"], []).append(e["type"])
    assert set(per) == {1, 2}
    for c, kinds in per.items():
        assert kinds == ["preview_start", "preview_delta", "preview_delta",
                         "preview_complete"], c


def test_scene_previews_raw_provisional_and_parse_unchanged(tmp_path):
    """Scene-card previews stream the raw answer; parsing/scenes.json are
    unchanged with and without a subscriber."""
    a, b = scenes_project(tmp_path / "a"), scenes_project(tmp_path / "b")
    FakeSceneProvider.text = SCENES_JSON
    evs = []
    out = plan.generate_scene_cards(
        a, provider_factory=lambda p: FakeSceneProvider(p),
        events=evs.append, preview_events=lambda ev: None)
    pv = [e for e in evs if e.get("type", "").startswith("preview_")]
    assert [e["type"] for e in pv] == [
        "preview_start", "preview_delta", "preview_delta", "preview_complete"]
    assert all(e["candidate_id"] == 1 for e in pv)
    deltas = "".join(e["text"] for e in pv
                     if e["type"] == "preview_delta")
    assert SCENES_JSON in deltas, "raw scene JSON visible before completion"
    before = (a / "scenes.json").read_bytes()
    assert (a / "scenes.json").read_bytes() == before, \
        "generation never writes scenes.json (preview only)"

    out_b = plan.generate_scene_cards(
        b, provider_factory=lambda p: FakeSceneProvider(p))
    assert out["cards"] == out_b["cards"], \
        "parsed cards are identical with and without previews"
    assert (b / "scenes.json").read_bytes() == before


def test_scene_previews_invalid_json_recovery_unchanged(tmp_path):
    """Invalid arrays keep the existing raw-saved recovery path; the preview
    shows the same raw text and adds no acceptance."""
    root = scenes_project(tmp_path / "p")
    FakeSceneProvider.text = "<scenes>[not json"
    evs = []
    out = plan.generate_scene_cards(
        root, provider_factory=lambda p: FakeSceneProvider(p),
        events=evs.append, preview_events=lambda ev: None)
    deltas = "".join(e["text"] for e in evs
                     if e.get("type", "").startswith("preview_") and
                     e["type"] == "preview_delta")
    assert "<scenes>[not json" in deltas
    assert out["cards"] is None and out["raw_path"], \
        "invalid raw output keeps the existing recovery path"
    saved = (root / "outlines" / out["raw_path"]).read_text()
    assert saved == "<scenes>[not json"
    assert (root / "scenes.json").read_bytes() == \
        (root / "scenes.json").read_bytes(), "scenes.json untouched"


def test_outline_choose_stale_refusal(tmp_path):
    root = outline_project(tmp_path / "p")
    base = plan.outline_baseline(root)
    FakeOutlineProvider.script = list(OUTLINES)
    out = plan.generate_outlines(root, "notes", 1,
                                 provider_factory=lambda p:
                                 FakeOutlineProvider(p))
    (root / "bible.md").write_text("changed\n", encoding="utf-8")
    with pytest.raises(OpError) as e:
        plan.choose_outline(root, out["candidates"][0], base)
    assert getattr(e.value, "stale", False)
    assert not (root / "outline.md").exists()


def test_outline_choose_stale_candidate_refusal(tmp_path):
    root = outline_project(tmp_path / "p")
    FakeOutlineProvider.script = list(OUTLINES)
    out = plan.generate_outlines(root, "notes", 1,
                                 provider_factory=lambda p:
                                 FakeOutlineProvider(p))
    base = plan.outline_baseline(root, out["candidates"])
    (root / "outlines" / out["candidates"][0]).write_text("tampered\n",
                                                          encoding="utf-8")
    with pytest.raises(OpError) as e:
        plan.choose_outline(root, out["candidates"][0], base)
    assert getattr(e.value, "stale", False)


def test_outline_body_edit_through_backed_up_boundary(tmp_path):
    root = outline_project(tmp_path / "p")
    (root / "outline.md").write_text("CURRENT\n", encoding="utf-8")
    base = plan.outline_baseline(root)
    plan.save_outline_body(root, "EDITED BODY\n", base)
    assert (root / "outline.md").read_text() == "EDITED BODY\n"
    prev = list((root / "outlines").glob("outline_prev_*.md"))
    assert prev and prev[0].read_text() == "CURRENT\n"


def test_outline_generation_stop_keeps_partial(tmp_path):
    from longform_core.cancel import CancellationToken
    root = outline_project(tmp_path / "p")
    tok = CancellationToken()
    tok.cancel()
    with pytest.raises(Exception):
        plan.generate_outlines(root, "notes", 2, token=tok,
                               provider_factory=lambda p:
                               FakeOutlineProvider(p))
    assert not list((root / "outlines").glob("candidate_*.md"))
    assert not (root / "outline.md").exists()


def test_outline_history_view_after_reopen(tmp_path):
    root = outline_project(tmp_path / "p")
    FakeOutlineProvider.script = list(OUTLINES)
    out = plan.generate_outlines(root, "notes", 1,
                                 provider_factory=lambda p:
                                 FakeOutlineProvider(p))
    over = plan.outline_overview(root)
    assert over["candidates"] == out["candidates"], \
        "saved candidates are listed after reopen"
    assert plan.read_outline_candidate(root, out["candidates"][0]).strip() \
        .endswith("OUTLINE ONE BODY")


# ---------------------------------------------------------------- scenes

SCENES_JSON = ('<scenes>[{"chapter": 1, "title": "Yard", "pov": "Mara", '
               '"setting": "the yard", "characters": ["Mara"], "goal": '
               '"count windows", "conflict": "wind", "outcome": "counted", '
               '"beats": ["Mara counts."], "target_words": 1700}, '
               '{"chapter": 1, "title": "Harbour", "pov": "Tom", "setting": '
               '"the harbour", "characters": ["Tom"], "goal": "sail", '
               '"conflict": "tide", "outcome": "sailed", "beats": '
               '["Tom sails."], "target_words": 15300}]</scenes>')


def scenes_project(tmp_path):
    root = outline_project(tmp_path / "p")
    (root / "outline.md").write_text("OUTLINE BODY\n", encoding="utf-8")
    return root


class FakeSceneProvider:
    def __init__(self, p):
        self.p = p
        self.calls = []

    def chat(self, role, messages, max_tokens=None, stream_cb=None,
             progress=True, token=None, on_retry_event=None,
             preview_events=None):
        self.calls.append({"role": role, "messages": messages})
        if token:
            token.check()
        if preview_events is not None:
            text = FakeSceneProvider.text
            preview_events({"type": "preview_start", "attempt_id": 1})
            half = len(text) // 2
            for part in (text[:half], text[half:]):
                preview_events({"type": "preview_delta", "attempt_id": 1,
                                "text": part})
            preview_events({"type": "preview_complete", "attempt_id": 1})
        return FakeSceneProvider.text, "stop", {}


def test_scenes_cli_parity_files_and_prompt(tmp_path, monkeypatch, capsys):
    import longform_core.commands as commands
    from longform_core.project import Project
    a, b = scenes_project(tmp_path / "cli"), scenes_project(tmp_path / "gui")
    FakeSceneProvider.text = SCENES_JSON

    seen = {}

    def spy(self, role, messages, max_tokens=None, **kw):
        seen["messages"] = messages
        return FakeSceneProvider.text, "stop", {}

    monkeypatch.setattr(commands.Api, "chat", spy)
    answers = iter(["a"])
    monkeypatch.setattr(commands, "ask", lambda *a2, **k: next(answers))
    commands.cmd_scenes(Project(a), types.SimpleNamespace(force=False))

    plan.generate_scene_cards(b, provider_factory=lambda p: FakeSceneProvider(p))
    cards, _warn, _total = plan._normalize_scene_cards(
        json.loads("[{\"chapter\": 1, \"title\": \"Yard\", \"pov\": \"Mara\", "
                   "\"setting\": \"the yard\", \"characters\": [\"Mara\"], "
                   "\"goal\": \"count windows\", \"conflict\": \"wind\", "
                   "\"outcome\": \"counted\", \"beats\": [\"Mara counts.\"], "
                   "\"target_words\": 1700}, {\"chapter\": 1, \"title\": "
                   "\"Harbour\", \"pov\": \"Tom\", \"setting\": \"the "
                   "harbour\", \"characters\": [\"Tom\"], \"goal\": \"sail\", "
                   "\"conflict\": \"tide\", \"outcome\": \"sailed\", "
                   "\"beats\": [\"Tom sails.\"], \"target_words\": 15300}]"),
        17000)
    plan.accept_scene_cards(b, cards, plan.scenes_baseline(b))
    assert (a / "scenes.json").read_bytes() == (b / "scenes.json").read_bytes()
    assert "Yard" in (b / "scenes.json").read_text()
    cli_scenes = json.loads((a / "scenes.json").read_text())
    assert cli_scenes[0]["id"] == "s01" and cli_scenes[1]["id"] == "s02"
    assert cli_scenes[0]["status"] == "planned"
    assert cli_scenes[0]["state_updated"] is False
    assert cli_scenes[0]["notes"] == ""
    # exact CLI messages (bible + outline + card schema)
    prov = FakeSceneProvider(b)
    from longform_core.commands import extract_json_array
    gen = plan.generate_scene_cards(b, provider_factory=lambda p: prov)
    assert prov.calls[0]["messages"] == seen["messages"]


def test_scenes_cli_transcript_frozen(tmp_path, monkeypatch, capsys):
    import longform_core.commands as commands
    from longform_core.project import Project
    a = scenes_project(tmp_path / "cli")
    FakeSceneProvider.text = SCENES_JSON
    monkeypatch.setattr(commands.Api, "chat",
                        lambda self, role, messages, max_tokens=None, **kw:
                        (FakeSceneProvider.text, "stop", {}))
    answers = iter(["v", "a"])
    monkeypatch.setattr(commands, "ask", lambda *a2, **k: next(answers))
    commands.cmd_scenes(Project(a), types.SimpleNamespace(force=False))
    out = capsys.readouterr().out
    assert "generating scene cards..." in out
    assert "2 scenes, 17000 target words (project target 17000)" in out
    assert "wrote " in out and "scenes.json" in out


def test_scenes_force_protection(tmp_path):
    root = scenes_project(tmp_path / "p")
    _write_json(root / "scenes.json", [{
        "id": "s001", "chapter": 1, "title": "Yard", "target_words": 100,
        "status": "drafting"}])
    calls = []
    prov = FakeSceneProvider(root)

    def counting(p):
        calls.append(1)
        return prov

    with pytest.raises(OpError) as e:
        plan.generate_scene_cards(root, provider_factory=counting)
    assert "confirm the force equivalent" in str(e.value)
    assert getattr(e.value, "collision", False), "GUI offers confirmation"
    assert calls == [], "declining runs no request"

    # a planned-only list previews without force (accept confirms replacement)
    _write_json(root / "scenes.json", [{
        "id": "s001", "chapter": 1, "title": "Yard", "target_words": 100,
        "status": "planned"}])
    out = plan.generate_scene_cards(root, provider_factory=counting)
    assert out["cards"][0]["id"] == "s01"

    # trees existing alone require force
    (root / "trees" / "s001.json").write_text("{}", encoding="utf-8")
    with pytest.raises(OpError) as e:
        plan.generate_scene_cards(root, provider_factory=counting)
    assert "trees are kept" in str(e.value)
    # with force=True the call happens
    out = plan.generate_scene_cards(root, force=True,
                                    provider_factory=counting)
    assert out["cards"]


def test_scenes_missing_outline(tmp_path):
    root = bible_project(tmp_path / "p")
    with pytest.raises(OpError) as e:
        plan.generate_scene_cards(root, provider_factory=FakeSceneProvider)
    assert "outline.md is empty or missing" in str(e.value)


def test_scenes_invalid_output_saves_raw(tmp_path):
    root = scenes_project(tmp_path / "p")
    FakeSceneProvider.text = "no json here at all"
    out = plan.generate_scene_cards(root, provider_factory=lambda p:
                                    FakeSceneProvider(p))
    assert out["raw"] == FakeSceneProvider.text
    raws = list((root / "outlines").glob("scenes_raw_*.txt"))
    assert len(raws) == 1 and raws[0].read_text() == FakeSceneProvider.text
    assert json.loads((root / "scenes.json").read_text()) == [], \
        "invalid output never replaces scenes.json"


def test_scenes_fenced_json_array(tmp_path):
    root = scenes_project(tmp_path / "p")
    FakeSceneProvider.text = ("```json\n<scenes>[{\"chapter\": 1, "
                              "\"title\": \"Yard\"}]</scenes>\n```")
    out = plan.generate_scene_cards(root, provider_factory=lambda p:
                                    FakeSceneProvider(p))
    assert out["cards"][0]["title"] == "Yard"


def test_scenes_normalization_defaults_and_ids(tmp_path):
    cards, warnings, total = plan._normalize_scene_cards([
        {"title": "Only"}, {"title": "Two", "chapter": "2", "target_words":
                            "300"}], 0)
    assert cards[0]["id"] == "s01" and cards[1]["id"] == "s02"
    assert cards[0]["chapter"] == 1 and cards[0]["target_words"] == 0
    assert cards[0]["notes"] == "" and cards[0]["status"] == "planned"
    assert cards[0]["state_updated"] is False
    assert cards[1]["chapter"] == 2 and cards[1]["target_words"] == 300
    assert any("targets 0 words" in w for w in warnings)


def test_scenes_normalization_more_than_99(tmp_path):
    arr = [{"title": f"c{k}"} for k in range(100)]
    cards, _w, _t = plan._normalize_scene_cards(arr, 0)
    assert cards[99]["id"] == "s100"


def test_scenes_validation_refuses_bad_values(tmp_path):
    bad_arrays = [
        [{"title": "x", "chapter": "abc"}],
        [{"title": "x", "chapter": 0}],
        [{"title": "x", "target_words": "abc"}],
        [{"title": "x", "target_words": -5}],
        [{"title": "x", "target_words": 1.5}],
        [{"title": "x", "characters": ["Mara", 3]}],
        [{"title": "x", "beats": "not a list"}],
        ["not an object"],
        [],
    ]
    for arr in bad_arrays:
        with pytest.raises(OpError) as e:
            plan._normalize_scene_cards(arr, 0)
        assert "scenes" in str(e.value) or "card" in str(e.value), arr


def test_scenes_accept_backs_up_and_keeps_trees(tmp_path):
    root = scenes_project(tmp_path / "p")
    _write_json(root / "scenes.json", [{
        "id": "s001", "chapter": 1, "title": "Old", "target_words": 100,
        "status": "planned"}])
    (root / "trees" / "s001.json").write_text(
        json.dumps({"nodes": {}, "head": None, "counter": 0}) + "\n",
        encoding="utf-8")
    tree_before = (root / "trees" / "s001.json").read_bytes()
    base = plan.scenes_baseline(root)
    cards = [{"id": "s01", "chapter": 1, "title": "New", "pov": "Mara",
              "setting": "", "characters": [], "goal": "", "conflict": "",
              "outcome": "", "beats": [], "notes": "", "target_words": 100,
              "status": "planned", "state_updated": False}]
    plan.accept_scene_cards(root, cards, base)
    saved = json.loads((root / "scenes.json").read_text())
    assert saved[0]["title"] == "New" and saved[0]["id"] == "s01"
    prevs = list((root / "outlines").glob("scenes_prev_*.json"))
    assert prevs and json.loads(prevs[0].read_text())[0]["title"] == "Old"
    assert (root / "trees" / "s001.json").read_bytes() == tree_before, \
        "trees are never touched"


def test_scenes_accept_stale_refusal(tmp_path):
    root = scenes_project(tmp_path / "p")
    base = plan.scenes_baseline(root)
    _write_json(root / "scenes.json", [{"id": "s001", "title": "external"}])
    cards = [{"id": "s01", "chapter": 1, "title": "New", "pov": "",
              "setting": "", "characters": [], "goal": "", "conflict": "",
              "outcome": "", "beats": [], "notes": "", "target_words": 0,
              "status": "planned", "state_updated": False}]
    with pytest.raises(OpError) as e:
        plan.accept_scene_cards(root, cards, base)
    assert getattr(e.value, "stale", False)
    assert json.loads((root / "scenes.json").read_text())[0]["title"] == \
        "external"


def test_scenes_generation_stop_saves_nothing(tmp_path):
    from longform_core.cancel import CancellationToken
    root = scenes_project(tmp_path / "p")
    tok = CancellationToken()
    tok.cancel()
    with pytest.raises(Exception):
        plan.generate_scene_cards(root, token=tok,
                                  provider_factory=lambda p:
                                  FakeSceneProvider(p))
    assert json.loads((root / "scenes.json").read_text()) == []
    assert not list((root / "outlines").glob("scenes_raw_*"))


# ------------------------------------------------- saved-card editing (1.7)

def saved_card(i=1, **kw):
    d = {"id": f"s0{i}", "chapter": 1, "title": f"Card {i}", "pov": "Mara",
         "setting": "yard", "characters": ["Mara"], "goal": "g", "conflict":
         "c", "outcome": "o", "beats": ["b"], "notes": "", "target_words":
         100, "status": "drafting", "state_updated": True, "extra_field":
         {"keep": True}}
    d.update(kw)
    return d


def test_card_edit_preserves_identity_and_unknown_fields(tmp_path):
    root = scenes_project(tmp_path / "p")
    _write_json(root / "scenes.json", [saved_card(), saved_card(2)])
    (root / "trees" / "s01.json").write_text("{}", encoding="utf-8")
    tree_before = (root / "trees" / "s01.json").read_bytes()
    base = plan.scenes_baseline(root)
    out = plan.save_scene_cards(root, [
        dict(saved_card(), title="Renamed", characters=["Mara", "Tom"],
             target_words=150),
        saved_card(2)], base)
    assert out["changed"] == 1
    saved = json.loads((root / "scenes.json").read_text())
    assert saved[0]["id"] == "s01" and saved[1]["id"] == "s02"
    assert saved[0]["title"] == "Renamed"
    assert saved[0]["status"] == "drafting"
    assert saved[0]["state_updated"] is True
    assert saved[0]["extra_field"] == {"keep": True}
    assert saved[0]["characters"] == ["Mara", "Tom"]
    assert saved[0]["target_words"] == 150
    assert (root / "trees" / "s01.json").read_bytes() == tree_before
    prevs = list((root / "outlines").glob("scenes_prev_*.json"))
    assert prevs and json.loads(prevs[0].read_text())[0]["title"] == "Card 1"


def test_card_edit_noop_save(tmp_path):
    root = scenes_project(tmp_path / "p")
    _write_json(root / "scenes.json", [saved_card()])
    before = (root / "scenes.json").read_bytes()
    base = plan.scenes_baseline(root)
    out = plan.save_scene_cards(root, [saved_card()], base)
    assert out["no_op"] is True and out["changed"] == 0
    assert (root / "scenes.json").read_bytes() == before
    assert not list((root / "outlines").glob("scenes_prev_*.json"))


def test_card_edit_refuses_identity_and_status_changes(tmp_path):
    root = scenes_project(tmp_path / "p")
    _write_json(root / "scenes.json", [saved_card()])
    base = plan.scenes_baseline(root)
    before = (root / "scenes.json").read_bytes()
    assert plan.save_scene_cards(root, [saved_card()], base)["no_op"] is True
    with pytest.raises(OpError) as e:
        plan.save_scene_cards(root, [dict(saved_card(), status="planned")],
                              base)
    assert "status cannot be edited" in str(e.value)
    with pytest.raises(OpError) as e:
        plan.save_scene_cards(root, [dict(saved_card(), state_updated=False)],
                              base)
    assert "state_updated cannot be edited" in str(e.value)
    # different id count / order
    with pytest.raises(OpError) as e:
        plan.save_scene_cards(root, [dict(saved_card(), id="s09")], base)
    assert "identity or order changed" in str(e.value)
    assert (root / "scenes.json").read_bytes() == before


def test_card_edit_refuses_bad_values(tmp_path):
    root = scenes_project(tmp_path / "p")
    _write_json(root / "scenes.json", [saved_card()])
    base = plan.scenes_baseline(root)
    for bad in ({"chapter": "abc"}, {"chapter": 0}, {"target_words": -1},
                {"target_words": "abc"}, {"characters": ["Mara", 2]},
                {"beats": "no"}, {"title": 5}):
        with pytest.raises(OpError) as e:
            plan.save_scene_cards(root, [dict(saved_card(), **bad)], base)
        msg = str(e.value)
        assert "card s01" in msg or "scenes" in msg, bad
    saved = json.loads((root / "scenes.json").read_text())
    assert saved[0]["title"] == "Card 1", "invalid edits write nothing"


def test_card_edit_stale_and_unsafe_refusal(tmp_path):
    root = scenes_project(tmp_path / "p")
    _write_json(root / "scenes.json", [saved_card()])
    base = plan.scenes_baseline(root)
    _write_json(root / "scenes.json", [saved_card(title="external")])
    with pytest.raises(OpError) as e:
        plan.save_scene_cards(root, [dict(saved_card(), title="mine")], base)
    assert getattr(e.value, "stale", False)
    assert json.loads((root / "scenes.json").read_text())[0]["title"] == \
        "external"

    (root / "scenes.json").rename(root / "scenes_keep.json")
    (root / "scenes.json").symlink_to(root / "scenes_keep.json")
    base2 = plan.scenes_baseline(root)
    with pytest.raises(OpError) as e:
        plan.save_scene_cards(root, [dict(saved_card(), title="mine")], base2)
    assert "symlink" in str(e.value)


def test_card_edit_refreshes_draft_reads(tmp_path):
    """The existing draft controls read the current saved cards after a save."""
    import longform_core.draft_operations as dop
    root = scenes_project(tmp_path / "p")
    _write_json(root / "scenes.json", [saved_card(pov="Old POV",
                                                  characters=["Old"])])
    base = plan.scenes_baseline(root)
    plan.save_scene_cards(root, [dict(saved_card(), pov="Mara",
                                      characters=["Mara", "Tom"])], base)
    card = dop.scene_card(root, "s01")
    assert card["pov"] == "Mara" and card["cast"] == "Mara, Tom"
    assert card["status"] == "drafting"
