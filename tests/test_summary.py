"""Tests for layered summary selection/rendering: pure layered_summary_core."""

import pytest

import json

import longform


def est(model, text):
    """Deterministic estimator: one token per 10 characters, plus 1 (like Project.est)."""
    return len(text or "") // 10 + 1


CFG = {"detailed_recent_scenes": 2}


def scene(sid, ch=1, title=""):
    return {"id": sid, "chapter": ch, "title": title}


def core(sums, scenes, idx, budget, cfg=None, estimator=est, root="/proj"):
    return longform.layered_summary_core(sums, cfg or CFG, scenes, idx, budget, estimator, "m", root)


def summaries(*scene_ids, arcs=()):
    return {
        "scenes": {sid: {"detailed": f"detailed {sid}", "brief": f"brief {sid}"} for sid in scene_ids},
        "arcs": list(arcs),
    }


def test_empty_entries_returns_empty_text():
    text, notes = core(summaries(), [scene("s1")], idx=0, budget=10 ** 6)
    assert (text, notes) == ("", [])


def test_scene_entries_detailed_and_brief():
    text, notes = core(summaries("s1", "s2"), [scene("s1"), scene("s2")], idx=2, budget=10 ** 6)
    # detailed_recent_scenes=2 covers both scenes here
    assert "### s1 - Ch 1: \ndetailed s1" in text
    assert "### s2 - Ch 1: \ndetailed s2" in text
    assert notes == []


def test_detailed_recent_scenes_window():
    scenes = [scene(f"s{i}") for i in range(4)]
    text, _ = core(summaries(*[s["id"] for s in scenes]), scenes, idx=4, budget=10 ** 6)
    assert "detailed s3" in text and "detailed s2" in text
    assert "detailed s1" not in text and "detailed s0" not in text
    assert "brief s0" in text


def test_missing_summary_note_and_marker():
    text, notes = core(summaries("s1"), [scene("s1"), scene("s2")], idx=2, budget=10 ** 6)
    assert "### s2 - Ch 1: \n[no summary recorded]" in text
    assert notes == ["s2 has no summary (run: update-state /proj --scene s2)"]


def test_arc_replaces_scenes_and_sorts():
    scenes = [scene(f"s{i}") for i in range(5)]
    sums = summaries("s0", "s1", "s2", "s3", "s4",
                     arcs=[{"from": "s3", "to": "s4", "text": "arc later"},
                           {"from": "s0", "to": "s1", "text": "arc early"}])
    text, notes = core(sums, scenes, idx=5, budget=10 ** 6)
    assert "Scenes s0-s1" in text and "arc early" in text
    assert "Scenes s3-s4" in text and "arc later" in text
    assert "### s0" not in text and "### s3" not in text
    assert text.index("arc early") < text.index("arc later")
    assert notes == []


def test_arc_spanning_or_after_idx_ignored():
    scenes = [scene(f"s{i}") for i in range(3)]
    sums = summaries("s0", "s1", "s2",
                     arcs=[{"from": "s0", "to": "s2", "text": "future arc"},
                           {"from": "s0", "to": "s9", "text": "unknown arc"}])
    text, _ = core(sums, scenes, idx=2, budget=10 ** 6)
    assert "future arc" not in text and "unknown arc" not in text
    assert "### s0" in text and "### s1" in text


def test_dropped_oldest_when_over_budget():
    scenes = [scene(f"s{i}") for i in range(5)]
    text, notes = core(summaries(*[s["id"] for s in scenes]), scenes, idx=5, budget=12)
    assert text.startswith("[3 earlier summary entries omitted for space]")
    assert notes == ["summary over budget: 3 oldest entries dropped (run: compress)"]
    # the newest scenes survive
    assert "brief s3" in text and "brief s4" in text


def test_detailed_trimmed_before_entries_dropped():
    scenes = [scene(f"s{i}") for i in range(4)]
    text, notes = core(summaries(*[s["id"] for s in scenes]), scenes, idx=4, budget=11)
    # every entry kept, but the detailed window shrank to brief text
    assert "[no" not in text and "omitted" not in text
    assert "detailed s0" not in text and "detailed s2" in text and "detailed s3" in text
    assert notes == []


def test_never_drops_last_entry():
    scenes = [scene("s0")]
    text, notes = core(summaries("s0"), scenes, idx=1, budget=1)
    assert "### s0" in text and notes == []


def test_wrapper_uses_project_state(tmp_path, monkeypatch):
    p = type("P", (), {})()
    p.root = tmp_path / "proj"
    p.root.mkdir()
    p.cfg = {"summary": {"detailed_recent_scenes": 1}}
    sums = {"scenes": {"s0": {"detailed": "D", "brief": "B"}}, "arcs": []}
    (p.root / "summaries.json").write_text(json.dumps(sums), encoding="utf-8")
    p.summaries = lambda: sums
    calls = []
    p.est = lambda model, text: calls.append((model, text)) or 1
    text, notes = longform.layered_summary(p, [scene("s0")], 1, 10 ** 6, "model-x")
    assert calls and calls[0][0] == "model-x"
    assert "### s0 - Ch 1: \nD" in text and notes == []
