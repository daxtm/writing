"""Offline model tests for the desktop reader's data snapshots (no Tk anywhere)."""

import os
import pathlib
import sys

import pytest

import longform_core.reader_model as rm
import reader_support as rs


@pytest.fixture
def load():
    def go(root, **kw):
        return rm.load_snapshot(root, **kw)
    return go


def assert_no_tk_in_modules():
    assert "tkinter" not in sys.modules, "reader_model must not import Tk"


def test_model_import_does_not_import_tk_or_cli_project(monkeypatch, tmp_path):
    """Prove in a fresh interpreter: no Tk, no Api, no shared Project, no die."""
    import subprocess
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = str(pathlib.Path(__file__).resolve().parents[1])
    code = (
        "import sys, longform_core.reader_model as rm\n"
        "assert 'tkinter' not in sys.modules\n"
        "assert 'longform_core.api' not in sys.modules\n"
        "assert 'longform_core.project' not in sys.modules\n"
        "assert 'longform_core.cli' not in sys.modules\n"
        "assert not hasattr(rm, 'die') and not hasattr(rm, 'Project')\n"
        "print('MODEL_CLEAN')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "MODEL_CLEAN" in r.stdout


# -- scene cards ---------------------------------------------------------------

def test_card_order_and_fields(tmp_path, load):
    p = rs.build_project(tmp_path / "p", scenes=[
        rs.scene("s001", chapter=2, title="A", status="drafting", target=1000),
        rs.scene("s002", chapter=1, title="B", status="planned", target=500),
    ], trees={"s001": rs.tree({"n1": rs.node("n1", None, "One two.")}, head="n1")})
    res = load(p)
    rows = res.snapshot.scenes
    assert [r.id for r in rows] == ["s001", "s002"], "file order is retained"
    assert rows[0].group == "Chapter 2" and rows[1].group == "Chapter 1"
    assert (rows[0].title, rows[0].status, rows[0].target_words) == ("A", "drafting", 1000)
    assert res.snapshot.trees["s001"].active_words == 2


def test_scene_without_chapter_groups_under_current_scenes(tmp_path, load):
    p = rs.build_project(tmp_path / "p", scenes=[
        rs.scene("s001", chapter=None), rs.scene("s002", chapter=3)])
    res = load(p)
    groups = {r.id: r.group for r in res.snapshot.scenes}
    assert groups == {"s001": "Current scenes", "s002": "Chapter 3"}

def test_unsafe_and_duplicate_scene_ids_refused(tmp_path, load):
    p = rs.build_project(tmp_path / "p", scenes=[
        rs.scene("s001"), rs.scene("../evil"), rs.scene("s001")])
    res = load(p)
    assert [r.id for r in res.snapshot.scenes] == ["s001"]
    assert any("invalid id" in w for w in res.warnings)
    assert any("duplicate scene s001" in w for w in res.warnings)


def test_no_scene_cards_empty_state(tmp_path, load):
    p = rs.build_project(tmp_path / "p", scenes=[])
    res = load(p)
    assert res.snapshot.scenes == []
    assert res.snapshot.actual_words == 0 and res.snapshot.words_complete


# -- trees ---------------------------------------------------------------------

def test_retained_tree_without_card_listed_separately(tmp_path, load):
    p = rs.build_project(tmp_path / "p", scenes=[rs.scene("s002")], trees={
        "s001": rs.tree({"n1": rs.node("n1", None, "kept prose.")}, head="n1"),
        "s002": rs.tree({"n1": rs.node("n1", None, "current.")}, head="n1"),
    })
    res = load(p)
    snap = res.snapshot
    assert set(snap.trees) == {"s001", "s002"}, "retained trees stay in the index"
    assert [r.id for r in snap.scenes] == ["s002"]
    assert snap.actual_words == 1, "retained trees never inflate current totals"


def test_all_saved_nodes_in_persisted_order_with_metadata(tmp_path, load):
    history = [{"time": "2026-01-02T00:00:00+00:00", "by": "user-edit",
                "text": "earlier words"}]
    p = rs.build_project(tmp_path / "p", trees={"s001": rs.tree({
        "n1": rs.node("n1", None, "root."),
        "n2": rs.node("n2", "n1", "left.", source="model", model="m",
                      steer="slow", ended=True, trimmed=False, history=history),
        "n3": rs.node("n3", "n1", "right.", created=rs.NOW),
    }, head="n1")})
    res = load(p)
    tv = res.snapshot.trees["s001"]
    assert tv.order == ["n1", "n2", "n3"], "all saved nodes, insertion order"
    n2 = tv.nodes["n2"]
    assert (n2.source, n2.model, n2.steer, n2.ended, n2.trimmed) == \
        ("model", "m", "slow", True, False)
    assert n2.history == history
    assert n2.word_count == 1
    n3 = tv.nodes["n3"]
    assert n3.source is None and n3.ended is None and n3.history == []


def test_children_computed_for_parent_navigation(tmp_path, load):
    p = rs.build_project(tmp_path / "p", trees={"s001": rs.tree({
        "n1": rs.node("n1", None, "root."),
        "n2": rs.node("n2", "n1", "a."),
        "n3": rs.node("n3", "n1", "b."),
        "n4": rs.node("n4", "n2", "child."),
    }, head="n4")})
    tv = load(p).snapshot.trees["s001"]
    assert tv.nodes["n1"].children == ["n2", "n3"]
    assert tv.nodes["n2"].children == ["n4"]


def test_no_head_is_empty_not_an_error(tmp_path, load):
    p = rs.build_project(tmp_path / "p", trees={"s001": rs.tree({
        "n1": rs.node("n1", None, "candidate.")}, head=None)})
    res = load(p)
    tv = res.snapshot.trees["s001"]
    assert tv.active_text == "" and tv.active_words == 0 and tv.head is None
    assert tv.nodes["n1"].text == "candidate."
    assert not res.warnings
    assert res.snapshot.words_complete


def test_active_chain_matches_tree_text_exactly(tmp_path, load):
    """Reuse existing Tree.text() semantics on the same in-memory tree data."""
    import longform

    t = rs.tree({
        "n1": rs.node("n1", None, "  Leading whitespace."),
        "n2": rs.node("n2", "n1", " joined mid-sentence", sep=""),
        "n3": rs.node("n3", "n2", "Third paragraph.", sep=" --- "),
        "n4": rs.node("n4", "n3", "inactive sibling.", sep="\n\n"),
    }, head="n3")
    p = rs.build_project(tmp_path / "p", trees={"s001": t})
    tv = load(p).snapshot.trees["s001"]
    real = longform.Tree.__new__(longform.Tree)
    real.d = t
    assert tv.active_text == real.text("n3")
    assert tv.active_ids == ["n1", "n2", "n3"]
    assert tv.nodes["n4"].on_active_path is False
    from longform_core.utils import words
    assert tv.active_words == words(tv.active_text)


def test_active_words_only_current_cards_partial_total(tmp_path, load):
    p = rs.build_project(tmp_path / "p", scenes=[rs.scene("s001"), rs.scene("s002")],
                         trees={
        "s001": rs.tree({"n1": rs.node("n1", None, "one two three.")}, head="n1"),
    })
    res = load(p)
    assert res.snapshot.actual_words == 3
    assert not res.snapshot.words_complete, "s002 tree missing -> partial total"


def test_tree_with_active_chain_broken_is_partial(tmp_path, load):
    p = rs.build_project(tmp_path / "p", scenes=[rs.scene("s001")], trees={
        "s001": rs.tree({"n1": rs.node("n1", None, "text.")},
                        head="missing")},
                        )
    res = load(p)
    tv = res.snapshot.trees["s001"]
    assert tv.active_words is None and tv.nodes["n1"].text == "text."
    assert not res.snapshot.words_complete


def test_missing_optional_files_give_empty_data(tmp_path, load):
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "project.json").write_text(
        rs.write_json(tmp_path / "cfg", {"title": "T", "target_words": 10}) or
        '{"title": "T", "target_words": 10}\n')
    res = load(tmp_path / "p")
    snap = res.snapshot
    assert snap.project.title == "T"
    assert snap.scenes == [] and snap.trees == {}
    assert snap.actual_words == 0 and snap.words_complete
    assert not res.warnings


def test_load_never_calls_die_or_reads_credentials(monkeypatch, tmp_path):
    import longform_core.utils as utils

    def _no_die(*_a, **_k):
        raise AssertionError("reader_model must not call die")
    monkeypatch.setattr(utils, "die", _no_die)
    monkeypatch.setenv("FEATHERLESS_API_KEY", "sk-secret-fake")
    p = tmp_path / "p"
    p.mkdir()
    (p / "project.json").write_text('{"title": "T", "target_words": 5}\n')
    (p / "trees").mkdir()
    (p / "trees" / "s001.json").write_text("{broken", encoding="utf-8")
    res = rm.load_snapshot(p)
    assert res.snapshot is not None and res.snapshot.trees["s001"].broken
    assert any("could not be read as JSON" in w for w in res.warnings)
    # the credential environment value never leaks into the snapshot
    assert "sk-secret-fake" not in repr(res.snapshot) + " ".join(res.warnings)


def test_defaults_for_absent_project_fields(tmp_path, load):
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "project.json").write_text("{}\n")
    res = load(tmp_path / "p")
    assert res.snapshot.project.title == "Untitled"
    assert res.snapshot.project.target_words == 17000


def test_invalid_required_config_prevents_snapshot(tmp_path, load):
    p = rs.build_project(tmp_path / "p", title=42)
    res = load(p)
    assert res.snapshot is None
    assert res.warnings and "42" not in " ".join(res.warnings)
    assert "project.json" in " ".join(res.warnings)


def test_malformed_project_json_prevents_snapshot(tmp_path, load):
    p = tmp_path / "p"
    p.mkdir()
    (p / "project.json").write_text("{not json", encoding="utf-8")
    res = load(p)
    assert res.snapshot is None
    assert "not json" not in " ".join(res.warnings)
