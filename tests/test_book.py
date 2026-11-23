"""Tests for lorebook/card parsing: pure parse_book_data and the parse_book wrapper."""

import json

import pytest

import longform


def entry(name=None, keys=(), secondary=(), content="", enabled=True, disable=False,
          constant=False, selective=False, logic=None, order=None, position=0,
          case=None, whole=None, **extra):
    e = {
        "comment": name,
        "key": keys.split(",") if isinstance(keys, str) else list(keys),
        "keysecondary": list(secondary),
        "content": content, "enabled": enabled, "disable": disable,
        "constant": constant, "selective": selective, "position": position,
        "caseSensitive": case, "matchWholeWords": whole,
    }
    if logic is not None:
        e["selectiveLogic"] = logic
    if order is not None:
        e["order"] = order
    e.update(extra)
    return e


def norm(**kw):
    """Expected normalized entry shape, with defaults filled in."""
    return {
        "name": "", "keys": [], "secondary": [], "content": "", "enabled": True,
        "constant": False, "selective": False, "logic": 0, "order": 100,
        "before": True, "case": None, "whole": None, **kw,
    }


def parse(d, stem="book"):
    return longform.parse_book_data(d, stem)


def test_not_a_card_and_not_entries_gives_none_and_empty():
    assert parse({}) == (None, [])
    assert parse({"entries": "nope"}) == (None, [])


def test_v2_card_character_book_entries():
    d = {"data": {"name": "Mara", "description": "a thief",
                  "character_book": {"entries": [entry(name="E1", keys=["mara"], content="C")]}}}
    card_name, entries = parse(d)
    assert card_name == "Mara"
    # the card description is synthesized ahead of the embedded book entries
    assert entries[0]["name"] == "card description" and entries[0]["content"] == "a thief"
    assert entries[1] == norm(name="E1", keys=["mara"], content="C")
    assert len(entries) == 2


def test_v1_card_at_top_level():
    d = {"name": "Tomas Stone", "description": "a watcher", "personality": "quiet"}
    card_name, entries = parse(d)
    assert card_name == "Tomas Stone"
    synth = entries[0]
    assert synth["name"] == "card description"
    assert synth["keys"] == ["Tomas Stone", "Tomas"]
    assert synth["content"] == "a watcher\n\nPersonality: quiet"
    assert synth["enabled"] is True and synth["constant"] is False and synth["order"] == 100


def test_card_name_falls_back_to_stem():
    d = {"data": {"name": "", "description": "x", "character_book": {"entries": []}}}
    card_name, _ = parse(d, stem="fallback_name")
    assert card_name == "fallback_name"


def test_card_without_description_no_synthetic_entry():
    d = {"data": {"name": "Mara", "character_book": {"entries": []}}}
    _, entries = parse(d)
    assert entries == []


def test_world_info_entries_dict():
    d = {"entries": {"0": entry(name="A", keys=["x"], position=1),
                     "1": entry(name="B", keys=["y"], position=0)}}
    card_name, entries = parse(d)
    assert card_name is None
    assert [e["name"] for e in entries] == ["A", "B"]
    assert entries[0]["before"] is False and entries[1]["before"] is True


def test_bare_list_of_entries():
    _, entries = parse([entry(name="L1", keys=["a"]), entry(name="L2", keys=["b"])])
    assert [e["name"] for e in entries] == ["L1", "L2"]


def test_non_dict_entries_skipped():
    _, entries = parse([entry(name="ok", keys=["a"]), "junk", 3, None])
    assert [e["name"] for e in entries] == ["ok"]


def test_key_normalization_string_and_list():
    _, entries = parse([entry(keys="a, b , ,c")])
    assert entries[0]["keys"] == ["a", "b", "c"]
    _, entries = parse([entry(keys=[1, " x ", "", None])])
    assert entries[0]["keys"] == ["1", "x", "None"]  # existing behavior: None stringifies


def test_secondary_keys_and_logic():
    e = parse([entry(secondary=["s1", "s2"], logic=3)])[1][0]
    assert e["secondary"] == ["s1", "s2"] and e["logic"] == 3


def test_enabled_disable_order_and_position():
    e = parse([entry(enabled=False)])[1][0]
    assert e["enabled"] is False
    e = parse([entry(disable=True)])[1][0]
    assert e["enabled"] is False
    e = parse([entry(order=7)])[1][0]
    assert e["order"] == 7
    e = parse([entry(keys=[], **{"insertion_order": 5})])[1][0]
    assert e["order"] == 5
    e = parse([entry(position="before_char")])[1][0]
    assert e["before"] is True
    e = parse([entry(position=1)])[1][0]
    assert e["before"] is False


def test_case_and_whole_passthrough():
    e = parse([entry(case=True, whole=False)])[1][0]
    assert e["case"] is True and e["whole"] is False


def test_name_empty_without_comment_or_name():
    e = parse([entry(keys=["first"], secondary=[])])[1][0]
    assert e["name"] == ""
    e = parse([entry(name="named")])[1][0]
    assert e["name"] == "named"


def test_wrapper_reads_json_file(tmp_path):
    path = tmp_path / "book.json"
    path.write_text(json.dumps([entry(name="W", keys=["k"])]), encoding="utf-8")
    card_name, entries = longform.parse_book(path)
    assert card_name is None
    assert [e["name"] for e in entries] == ["W"]


def test_wrapper_png_no_card_warns(tmp_path, capsys):
    path = tmp_path / "empty.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert longform.parse_book(path) == (None, [])
    assert "no character card data found" in capsys.readouterr().out


def test_wrapper_bad_json_dies(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit):
        longform.parse_book(path)
