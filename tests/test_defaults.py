"""Reviewed bundled new-project defaults (project-defaults-full-init 1.2).

The resources under longform_core/resources/ are application-owned reviewed
derivatives (ADR-0010); the owner's original source files are blocked from all
test reads by the conftest guard. Synthetic variants — never real content —
exercise the fail-closed validation.
"""

import json
from pathlib import Path

import pytest

from longform_core import defaults as dfl
from longform_core.config import DEFAULT_CONFIG
from longform_core.draft_operations import OpError

RESOURCES = Path(dfl.__file__).resolve().parent / "resources"


# ------------------------------------------------------------- the resources

def test_bundled_defaults_hold_reviewed_supported_values():
    cfg = dfl.project_defaults()
    assert cfg["title"] == "Untitled"
    assert cfg["target_words"] == 17000
    # forced sanitizing overrides
    assert cfg["api_key"] == "", "no credential may ship in the defaults"
    assert cfg["api_key_env"] == "FEATHERLESS_API_KEY"
    assert cfg["roles"]["writer"]["preset"] == "writer_preset.json", \
        "the preset path must stay project-relative"
    # reviewed nonsecret selections
    assert cfg["roles"]["writer"]["model"] == "TheDrummer/Anubis-70B-v1.2"
    assert cfg["roles"]["planner"]["model"] == \
        "huihui-ai/Huihui-Qwen3.8-27B-abliterated"
    assert cfg["roles"]["writer"]["preset_overrides"] == \
        {"temp": 1.06, "genamt": 3000, "max_length": 32768}
    assert cfg["roles"]["writer"]["passage_words"] == 1500
    assert cfg["roles"]["planner"]["thinking"] is False
    assert cfg["budget_tokens"]["bible"] == 2400
    assert cfg["ngram"] == {"n": 5, "min_count": 3, "top": 40}
    assert len(cfg["banned_phrases"]) == 14


def test_bundled_preset_is_a_valid_usable_master_export():
    data = dfl.writer_preset_bytes()
    parsed = json.loads(data.decode("utf-8"))
    for k in ("instruct", "context", "sysprompt", "preset"):
        assert isinstance(parsed[k], dict), k
    from longform_core.prompt import writer_sampling
    params, extra, ignored = writer_sampling(parsed, lambda s: s)
    assert params["temperature"] == 1.06
    assert params["max_tokens"] == 300
    assert parsed["preset"]["max_length"] == 24576


def test_every_call_returns_a_fresh_independent_copy():
    first = dfl.project_defaults()
    first["target_words"] = 1
    first["roles"]["writer"]["preset_overrides"]["temp"] = 9.9
    first["banned_phrases"].append("sentinel")
    second = dfl.project_defaults()
    assert second["target_words"] == 17000
    assert second["roles"]["writer"]["preset_overrides"]["temp"] == 1.06
    assert "sentinel" not in second["banned_phrases"]
    assert second != first


def test_bundled_defaults_do_not_replace_existing_project_fallbacks():
    """DEFAULT_CONFIG stays the old-project fallback contract; the defaults
    are a separate asset (init-only)."""
    cfg = dfl.project_defaults()
    assert cfg["roles"]["writer"]["passage_words"] != \
        DEFAULT_CONFIG["roles"]["writer"]["passage_words"]
    assert DEFAULT_CONFIG["roles"]["writer"]["passage_words"] == 220


# --------------------------------------------------- fail-closed validation

def _variant(tmp_path, name, mutate):
    raw = json.loads((RESOURCES / name).read_text(encoding="utf-8"))
    mutate(raw)
    return raw


def test_unknown_defaults_field_is_rejected_without_echoing_values():
    payload = _variant({}, "project_defaults.json",
                       lambda d: d.update({"auth_token": "sk-sentinel"}))
    with pytest.raises(dfl.DefaultsError) as e:
        dfl.validate_defaults(payload)
    msg = str(e.value)
    assert "auth_token" in msg
    assert "sk-sentinel" not in msg, "values are never echoed"


def test_unknown_nested_defaults_field_is_rejected():
    def mutate(d):
        d["roles"]["planner"]["local_path"] = "/home/sentinel/story"
    payload = _variant({}, "project_defaults.json", mutate)
    with pytest.raises(dfl.DefaultsError) as e:
        dfl.validate_defaults(payload)
    msg = str(e.value)
    assert "roles.planner.local_path" in msg
    assert "/home/sentinel" not in msg


def test_forced_field_deviation_is_rejected_without_echoing_the_value():
    def mutate(d):
        d["api_key"] = "sk-real-looking-sentinel"
    payload = _variant({}, "project_defaults.json", mutate)
    with pytest.raises(dfl.DefaultsError) as e:
        dfl.validate_defaults(payload)
    assert "api_key" in str(e.value)
    assert "sk-real-looking-sentinel" not in str(e.value)


def test_wrong_typed_defaults_field_is_rejected():
    payload = _variant({}, "project_defaults.json",
                       lambda d: d.update({"target_words": "big"}))
    with pytest.raises(dfl.DefaultsError) as e:
        dfl.validate_defaults(payload)
    assert "target_words" in str(e.value)


def test_unknown_preset_field_is_rejected_without_echoing_values():
    def mutate(d):
        d["preset"]["home_dir"] = "/home/sentinel"
    payload = _variant({}, "writer_preset.json", mutate)
    with pytest.raises(dfl.DefaultsError) as e:
        dfl.validate_preset(payload)
    assert "preset.home_dir" in str(e.value)
    assert "/home/sentinel" not in str(e.value)


def test_preset_without_master_export_keys_is_rejected():
    with pytest.raises(dfl.DefaultsError) as e:
        dfl.validate_preset({"instruct": {}, "context": {}})
    assert "sysprompt" in str(e.value)


# ---------------------------------------------- missing / corrupt resources

@pytest.fixture
def empty_installation(monkeypatch, tmp_path):
    monkeypatch.setattr(dfl, "resource_candidates",
                        lambda: [tmp_path / "nowhere"])
    return tmp_path / "nowhere"


def test_missing_defaults_resource_fails_closed(empty_installation):
    with pytest.raises(dfl.DefaultsError) as e:
        dfl.project_defaults()
    msg = str(e.value)
    assert "project_defaults.json" in msg
    assert "missing" in msg or "reinstall" in msg


def test_missing_preset_resource_fails_closed(empty_installation):
    with pytest.raises(dfl.DefaultsError) as e:
        dfl.writer_preset_bytes()
    assert "writer_preset.json" in str(e.value)


def test_corrupt_defaults_resource_fails_closed(monkeypatch, tmp_path):
    d = tmp_path / "res"
    d.mkdir()
    (d / "project_defaults.json").write_text("{corrupt", encoding="utf-8")
    monkeypatch.setattr(dfl, "resource_candidates", lambda: [d])
    with pytest.raises(dfl.DefaultsError) as e:
        dfl.project_defaults()
    assert "not valid JSON" in str(e.value)


def test_corrupt_preset_resource_fails_closed(monkeypatch, tmp_path):
    d = tmp_path / "res"
    d.mkdir()
    (d / "writer_preset.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(dfl, "resource_candidates", lambda: [d])
    with pytest.raises(dfl.DefaultsError) as e:
        dfl.writer_preset_bytes()
    assert "not a JSON object" in str(e.value) or "master export" in str(e.value)


def test_loader_is_independent_of_the_current_directory(monkeypatch, tmp_path):
    """Resource resolution never depends on cwd; only the candidates list."""
    monkeypatch.chdir(tmp_path)
    cfg = dfl.project_defaults()
    assert cfg["title"] == "Untitled"


def test_original_sources_are_blocked_from_test_reads():
    """The conftest guard refuses the owner's exact original paths; the
    reviewed resources are read instead."""
    from tests.conftest import ORIGINAL_SOURCES
    for original in ORIGINAL_SOURCES:
        with pytest.raises(AssertionError):
            original.read_text(encoding="utf-8")
    assert (RESOURCES / "project_defaults.json").is_file()
    assert (RESOURCES / "writer_preset.json").is_file()


def test_init_level_errors_are_not_defaults_leaks():
    """DefaultsError is distinct from init's OpError surface but sanitized the
    same way: type/path only."""
    assert not issubclass(dfl.DefaultsError, OpError)
