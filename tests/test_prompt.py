"""Tests for writer sampling extraction and story-string rendering."""

import longform


# --------------------------------------------------------------------------- writer_sampling


def sampling(preset_dict, instruct=None, mac=None):
    return longform.writer_sampling(
        {"preset": preset_dict, "instruct": instruct or {}, "context": {}, "sysprompt": {}},
        mac or (lambda s: s))


def test_writer_sampling_defaults():
    params, extra, ignored = sampling({})
    assert params == {"temperature": 1.0}
    assert extra == {} and ignored == []


def test_writer_sampling_numeric_conversion():
    params, _, _ = sampling({
        "temp": "0.7", "top_p": 0.9, "min_p": 0.05, "rep_pen": 1.1,
        "freq_pen": 0.2, "presence_pen": 0.1, "top_k": "40", "genamt": "512",
    })
    assert params == {
        "temperature": 0.7, "top_p": 0.9, "min_p": 0.05, "repetition_penalty": 1.1,
        "frequency_penalty": 0.2, "presence_penalty": 0.1, "top_k": 40, "max_tokens": 512,
    }


def test_writer_sampling_zero_and_missing_samplers_omitted():
    params, _, _ = sampling({"top_k": 0, "top_p": None, "genamt": 0})
    assert params == {"temperature": 1.0}


def test_writer_sampling_stop_sequence_macro():
    params, _, _ = sampling({}, instruct={"stop_sequence": "{{user}} speaks"},
                            mac=lambda s: s.replace("{{user}}", "Auth"))
    assert params["stop"] == ["Auth speaks"]


def test_writer_sampling_empty_stop_ignored():
    params, _, _ = sampling({}, instruct={"stop_sequence": ""})
    assert "stop" not in params


def test_writer_sampling_dry_extra():
    params, extra, _ = sampling({
        "dry_multiplier": 0.8, "dry_base": 1.5, "dry_allowed_length": 3,
        "dry_penalty_last_n": 16, "dry_sequence_breakers": '["\\n\\n"]',
    })
    assert extra == {
        "dry_multiplier": 0.8, "dry_base": 1.5, "dry_allowed_length": 3,
        "dry_penalty_last_n": 16, "dry_sequence_breakers": ["\n\n"],
    }


def test_writer_sampling_dry_defaults():
    _, extra, _ = sampling({"dry_multiplier": 0.8})
    assert extra == {"dry_multiplier": 0.8, "dry_base": 1.75, "dry_allowed_length": 2, "dry_sequence_breakers": []}


def test_writer_sampling_dry_off_or_malformed_breakers():
    _, extra, _ = sampling({"dry_multiplier": 0})
    assert extra == {}
    _, extra, _ = sampling({"dry_multiplier": None})
    assert extra == {}
    _, extra, _ = sampling({"dry_multiplier": 0.8, "dry_sequence_breakers": "not json"})
    assert extra["dry_sequence_breakers"] == []


def test_writer_sampling_unsendable_samplers_reported():
    _, _, ignored = sampling({"typical_p": 0.95, "mirostat_mode": 1, "tfs": 1.0, "top_a": 0})
    assert ignored == ["typical_p", "mirostat_mode"]


def test_writer_sampling_rep_pen_range_only_when_rep_pen_active():
    _, _, ignored = sampling({"rep_pen_range": 2048, "rep_pen": 1.1})
    assert ignored == ["rep_pen_range"]
    _, _, ignored = sampling({"rep_pen_range": 2048})
    assert ignored == []
    _, _, ignored = sampling({"rep_pen_range": 0, "rep_pen": 1.1})
    assert ignored == []


# --------------------------------------------------------------------------- render_story_string


def render(tpl, fields):
    return longform.render_story_string(tpl, fields)


def test_render_expands_fields_and_missing_to_empty():
    assert render("{{description}}|{{nope}}|", {"description": "D"}) == "D||"


def test_render_conditionals():
    tpl = "{{#if system}}{{system}}\n{{/if}}{{#if missing}}SHOULD NOT APPEAR{{/if}}body"
    assert render(tpl, {"system": "S"}) == "S\nbody"
    assert render(tpl, {}) == "body"


def test_render_trim_removes_surrounding_newlines():
    assert render("A\n\n{{trim}}\n\nB", {}) == "AB"


def test_render_trim_between_fields():
    tpl = "{{description}}{{trim}}{{wiAfter}}"
    assert render(tpl, {"description": "D", "wiAfter": "W"}) == "DW"
    assert render(tpl, {"description": "D"}) == "D"


def test_render_multiline_field_value():
    assert render("{{scenario}}", {"scenario": "line1\nline2"}) == "line1\nline2"
