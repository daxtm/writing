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
