"""Tests for the deterministic checker: pure check_report helper and the check CLI."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import longform

REPO = Path(longform.__file__).resolve().parent
STAMP_RE = re.compile(r"\(\d{4}-\d{2}-\d{2}T[^)]*\)")


def normalize(report):
    return STAMP_RE.sub("(STAMP)", report)


# --------------------------------------------------------------------------- fixtures

def make_tree(nodes, head):
    """nodes: list of (nid, parent, text)."""
    return {
        "nodes": {nid: {"id": nid, "parent": parent, "text": text} for nid, parent, text in nodes},
        "head": head,
        "counter": len(nodes),
    }


def make_project(root, scenes, trees, banned=None):
    root.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(json.dumps(longform.DEFAULT_CONFIG))
    if banned is not None:
        cfg["banned_phrases"] = banned
    (root / "project.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    (root / "scenes.json").write_text(json.dumps(scenes, indent=2) + "\n", encoding="utf-8")
    (root / "trees").mkdir(exist_ok=True)
    for sid, data in trees.items():
        (root / "trees" / f"{sid}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return root


def run_check(root, extra=(), env=None):
    cmd = [sys.executable, str(REPO / "longform.py"), "check", str(root), *extra]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)


SCENE_TEXT_1 = "Shivers down her spine. The red dragon flew over green hills. " * 3
SCENE_TEXT_2 = "Shivers down elsewhere."


@pytest.fixture
def project(tmp_path):
    """Two scenes: s001 has a banned phrase, repeats and an inactive branch; s002 one hit."""
    root = tmp_path / "proj"
    scenes = [
        {"id": "s001", "chapter": 1, "title": "One", "characters": [], "target_words": 100},
        {"id": "s002", "chapter": 1, "title": "Two", "characters": [], "target_words": 100},
    ]
    trees = {
        "s001": make_tree(
            [
                ("n1", None, "A cold wind rose."),
                ("n2", "n1", SCENE_TEXT_1),
                ("n3", "n1", "shivers down on an inactive branch"),
            ],
            head="n2",
        ),
        "s002": make_tree([("n1", None, SCENE_TEXT_2)], head="n1"),
    }
    make_project(root, scenes, trees, banned=["shivers down", "   "])
    return root


def expected_scene_texts(root):
    del root
    return [
        ("s001", [("n1", "A cold wind rose."), ("n2", SCENE_TEXT_1)], "A cold wind rose.\n\n" + SCENE_TEXT_1),
        ("s002", [("n1", SCENE_TEXT_2)], SCENE_TEXT_2),
    ]


# --------------------------------------------------------------------------- CLI stdout/saved report


def test_check_cli_all_scenes(project, net_guard_env):
    r = run_check(project, env=net_guard_env)
    assert r.returncode == 0, r.stderr
    saved = (project / "checks" / "all.md").read_text(encoding="utf-8")
    printed, _, wrote = r.stdout.rpartition("\nwrote ")
    assert normalize(printed) == normalize(saved), "stdout report must equal the saved report"
    assert wrote == str(project / "checks" / "all.md") + "\n"
    assert normalize(saved).startswith("# Check all scenes (STAMP)\n\n## Banned phrases\n\n")
    assert '- s001/n2: "shivers down" ... ' in saved
    assert '- s002/n1: "shivers down" ... ' in saved
    assert '3x "the red dragon flew over" in s001' in saved
    assert "n3" not in saved, "inactive branch must not appear"


def test_check_cli_selected_scene(project, net_guard_env):
    r = run_check(project, extra=["--scene", "s001"], env=net_guard_env)
    assert r.returncode == 0, r.stderr
    saved = (project / "checks" / "s001.md").read_text(encoding="utf-8")
    printed, _, wrote = r.stdout.rpartition("\nwrote ")
    assert normalize(printed) == normalize(saved)
    assert wrote == str(project / "checks" / "s001.md") + "\n"
    assert normalize(saved).startswith("# Check scene s001 (STAMP)\n\n## Banned phrases\n\n")
    assert "- s002" not in saved
    assert '- s001/n2: "shivers down" ... ' in saved
    assert '3x "the red dragon flew over" in s001' in saved


def test_check_pure_cli_parity(project, net_guard_env):
    """The pure helper, given the same inputs, reproduces the CLI report byte for byte."""
    expected = longform.check_report(expected_scene_texts(project), ["shivers down"], 5, 3, 40,
                                     "# Check all scenes (STAMP)")
    r = run_check(project, env=net_guard_env)
    assert r.returncode == 0, r.stderr
    saved = (project / "checks" / "all.md").read_text(encoding="utf-8")
    assert normalize(saved) == expected


# --------------------------------------------------------------------------- pure helper edge cases


def report(scene_texts, banned=(), n=5, min_count=3, top=40, title="# T"):
    return longform.check_report(list(scene_texts), list(banned), n, min_count, top, title)


def sc(sid, text):
    """One-scene input shape: (scene_id, [(node_id, node_text)], joined_active_text)."""
    return (sid, [("n1", text)], text)


def gram_lines(r):
    return [ln for ln in r.splitlines() if ln.startswith("- ") and "x \"" in ln]


def test_check_report_empty_scenes_and_no_hits():
    r = report([], title="# T")
    assert r == "# T\n\n## Banned phrases\n\n(none)\n\n## Repeated 5-grams (count >= 3)\n\n(none)\n"
    r = report([("s1", [], "")])
    assert "(none)" in r


def test_check_report_banned_case_insensitive_and_snippet():
    r = report([sc("s1", "She felt SHIVERS DOWN her spine.")], banned=("shivers down",))
    assert '- s1/n1: "shivers down" ... She felt SHIVERS DOWN her spine. ...' in r


def test_check_report_snippet_collapses_whitespace_and_bounds():
    text = "x" * 60 + "shivers down\n\tmore" + "y" * 60
    r = report([sc("s1", text)], banned=("shivers down",))
    snippet = re.search(r"\.\.\. (.+) \.\.\.", r).group(1)
    assert "\n" not in snippet and "\t" not in snippet and "  " not in snippet
    assert "xxxx" in snippet and "yyyy" in snippet


def test_check_report_multiple_banned_matches_per_node():
    r = report([sc("s1", "shivers down and shivers down again")], banned=("shivers down",))
    assert r.count('- s1/n1: "shivers down" ...') == 2


def test_check_report_whitespace_only_banned_ignored():
    r = report([sc("s1", "plain text")], banned=("  ", "\t", ""))
    assert "(none)" in r


def test_check_report_stopword_grams_skipped():
    text = "the of and to in red dragon the of and to in red dragon"
    r = report([sc("s1", text)], n=5, min_count=3)
    assert "(none)" in r, "grams with >= n-1 stopwords must be filtered"


def test_check_report_threshold_boundary():
    text = "red dragon red dragon"  # (red, dragon) x2, (dragon, red) x1 at n=2
    r = report([sc("s1", text)], n=2, min_count=2)
    assert '2x "red dragon"' in r
    r = report([sc("s1", text)], n=2, min_count=3)
    assert "2x" not in r and "(none)" in r


def test_check_report_ties_sorted_by_gram_reverse():
    text = "red dragon blue dragon red dragon blue dragon"
    r = report([sc("s1", text)], n=2, min_count=2)
    grams = [ln.split('"')[1] for ln in gram_lines(r)]
    assert grams == ["red dragon", "dragon blue", "blue dragon"]


def test_check_report_top_limit():
    text = "aa bb aa bb aa bb aa bb aa bb"  # (aa,bb) x5, (bb,aa) x4
    r = report([sc("s1", text)], n=2, min_count=2, top=1)
    lines = gram_lines(r)
    assert len(lines) == 1 and '5x "aa bb"' in lines[0]


def test_check_report_locations_sorted_and_scoped():
    r = report([sc("s2", "red dragon green"), sc("s1", "red dragon blue")], n=2, min_count=1)
    assert '2x "red dragon" in s1, s2' in r
    assert '1x "dragon green" in s2' in r
    assert '1x "dragon blue" in s1' in r


def test_check_report_no_cross_scene_ngrams():
    r = report([sc("s1", "red dragon"), sc("s2", "red dragon")], n=2, min_count=2)
    assert "(none)" in r


def test_check_report_grams_span_joined_nodes_within_scene():
    r = report([("s1", [("n1", "red"), ("n2", "dragon")], "red dragon")], n=2, min_count=1)
    assert '1x "red dragon" in s1' in r
