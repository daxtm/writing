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
    """Prove in a fresh interpreter: no Tk, no PySide6, no Api, no Project, no die."""
    import subprocess
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = str(pathlib.Path(__file__).resolve().parents[1])
    code = (
        "import sys, longform_core.reader_model as rm\n"
        "assert 'tkinter' not in sys.modules\n"
        "assert 'PySide6' not in sys.modules\n"
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


# -- tree-level steering (allowlisted for the gui shell) -----------------------

def test_tree_level_steer_exposed_with_defaults(tmp_path, load):
    t1 = rs.tree({"n1": rs.node("n1", None, "one.")}, head="n1")
    t2 = rs.tree({"n1": rs.node("n1", None, "two.")}, head="n1")
    t2["steer"] = "slow burn, past tense"
    p = rs.build_project(tmp_path / "p", scenes=[rs.scene("s001"), rs.scene("s002")],
                         trees={"s001": t1, "s002": t2})
    snap = load(p).snapshot
    assert snap.trees["s001"].steer == "", "missing tree steer defaults to empty"
    assert snap.trees["s001"].steer_valid
    assert snap.trees["s002"].steer == "slow burn, past tense"
    assert snap.trees["s002"].steer_valid


def test_non_string_tree_steer_warns_and_disables_editing(tmp_path, load):
    t = rs.tree({"n1": rs.node("n1", None, "one.")}, head="n1")
    t["steer"] = 42
    p = rs.build_project(tmp_path / "p", scenes=[rs.scene("s001")], trees={"s001": t})
    res = load(p)
    tv = res.snapshot.trees["s001"]
    assert not tv.steer_valid
    assert any("steering is not text" in w for w in res.warnings), res.warnings
    blob = repr(res.snapshot)
    assert "42" not in blob, "the invalid value is not echoed"


def test_broken_tree_keeps_default_steer_fields(tmp_path, load):
    p = rs.build_project(tmp_path / "p", scenes=[rs.scene("s001")])
    (p / "trees" / "s001.json").write_text("{broken", encoding="utf-8")
    res = load(p)
    tv = res.snapshot.trees["s001"]
    assert tv.broken and tv.steer == "" and tv.steer_valid


# -- notes ---------------------------------------------------------------------

def test_all_note_sources_read_with_backups_sorted(tmp_path, load):
    p = rs.build_project(
        tmp_path / "p",
        scenes=[rs.scene("s001")],
        trees={"s001": rs.tree({"n1": rs.node("n1", None, "One.")}, head="n1")},
        bible="# Story bible\n\n**markup stays literal**\n",
        state="# Continuity state\n\n- Mira: tower\n",
        summaries={"scenes": {"s001": {"detailed": "DETAIL FULL", "brief": "brief B",
                                       "updated": "2026-01-05T00:00:00+00:00",
                                       "text_hash": "n0t4hash",
                                       "secret_field": "SUMSECRET"}},
                   "arcs": [{"from": "s001", "to": "s002", "text": "ARC BODY",
                             "updated": "2026-01-06T00:00:00+00:00"}]},
        checks={"s001.md": "CHECK BODY"},
        critiques={"s001.md": "CRITIQUE BODY", "s001_prev_20260101.md": "OLD CRITIQUE"},
    )
    res = load(p)
    notes = res.snapshot.notes
    assert "**markup stays literal**" in notes.bible
    assert "Mira: tower" in notes.state
    s = notes.summaries.scenes["s001"]
    assert (s.detailed, s.brief) == ("DETAIL FULL", "brief B")
    assert s.updated.startswith("2026-01-05")
    assert s.detailed and "n0t4hash" not in repr(res.snapshot), \
        "internal fields are not exposed"
    assert "SUMSECRET" not in repr(res.snapshot)
    a = notes.summaries.arcs[0]
    assert (a.from_id, a.to_id, a.text) == ("s001", "s002", "ARC BODY")
    assert [f.name for f in notes.checks] == ["s001.md"]
    assert [f.name for f in notes.critiques] == ["s001.md", "s001_prev_20260101.md"], \
        "backups are listed in sorted order"
    assert "OLD CRITIQUE" in notes.critiques[1].text


def test_missing_note_sources_are_empty_without_warnings(tmp_path, load):
    p = rs.build_project(tmp_path / "p")
    (p / "summaries.json").unlink()
    res = load(p)
    notes = res.snapshot.notes
    assert notes.bible is None and notes.state is None
    assert notes.summaries is None
    assert notes.checks == [] and notes.critiques == []
    assert not res.warnings


def test_malformed_summaries_warn_and_recover(tmp_path, load):
    p = rs.build_project(tmp_path / "p", bible="BIBLE TEXT")
    (p / "summaries.json").write_text("{broken", encoding="utf-8")
    res = load(p)
    assert res.snapshot.notes.summaries is None
    assert "BIBLE TEXT" in res.snapshot.notes.bible, "unrelated sources still load"
    assert "summaries.json" in " ".join(res.warnings)
    rs.write_json(p / "summaries.json",
                  {"scenes": {"s001": {"detailed": "BACK", "brief": None,
                                       "updated": None}}, "arcs": []})
    res2 = load(p, cache=rm.SourceCache())
    assert res2.snapshot.notes.summaries.scenes["s001"].detailed == "BACK"
    assert not res2.warnings


def test_unknown_summary_shapes_skipped_with_warning(tmp_path, load):
    p = rs.build_project(tmp_path / "p", summaries={
        "scenes": {"s001": "not-a-dict"},
        "arcs": [{"from": 1, "to": "s002", "text": "x"}]})
    res = load(p)
    notes = res.snapshot.notes
    assert notes.summaries is not None and notes.summaries.scenes == {}
    assert notes.summaries.arcs == []
    assert any("invalid scene summary" in w for w in res.warnings)
    assert any("invalid arc summary" in w for w in res.warnings)


# -- broken trees, cycles, dangling links --------------------------------------

def test_parent_cycle_keeps_node_text_and_warns(tmp_path, load):
    p = rs.build_project(tmp_path / "p", scenes=[rs.scene("s001")], trees={
        "s001": rs.tree({
            "n1": rs.node("n1", "n2", "first text."),
            "n2": rs.node("n2", "n1", "second text."),
        }, head="n1")})
    res = load(p)
    tv = res.snapshot.trees["s001"]
    assert tv.active_text is None and tv.active_words is None
    assert any("active chain is broken" in w for w in res.warnings)
    assert tv.nodes["n1"].text == "first text."
    assert not res.snapshot.words_complete


def test_dangling_head_and_parent_warn_nodes_readable(tmp_path, load):
    p = rs.build_project(tmp_path / "p", trees={"s001": rs.tree({
        "n1": rs.node("n1", None, "root text."),
        "n2": rs.node("n2", "missing", "orphan text."),
    }, head="nope")})
    res = load(p)
    tv = res.snapshot.trees["s001"]
    assert tv.active_text is None
    assert any("head references a missing node" in w for w in res.warnings)
    assert tv.nodes["n2"].link_ok is False
    assert tv.nodes["n2"].text == "orphan text."
    assert tv.nodes["n1"].link_ok is True


# -- read failures, unsafe ids, symlinks ----------------------------------------

def test_unreadable_current_tree_is_partial_with_warning(tmp_path, load):
    p = rs.build_project(tmp_path / "p", scenes=[rs.scene("s001")])
    (p / "trees" / "s001.json").mkdir(parents=True)  # a directory where JSON is expected
    res = load(p)
    tv = res.snapshot.trees["s001"]
    assert tv.broken and tv.active_words is None
    assert any("trees/s001.json" in w for w in res.warnings)
    assert not res.snapshot.words_complete


def test_unsafe_tree_stem_skipped_with_warning(tmp_path, load):
    p = rs.build_project(tmp_path / "p")
    rs.write_text(p / "trees" / "bad id.json", '{"nodes": {}}')
    res = load(p)
    assert res.snapshot.trees == {}
    assert any("unsafe id" in w for w in res.warnings)
    assert "bad id.json" in " ".join(res.warnings)  # relative name, sanitized


def test_symlinked_sources_refused_and_contents_hidden(tmp_path, load):
    outside = tmp_path / "outside"
    outside.mkdir()
    rs.write_text(outside / "secret.md", "OUTSIDE SECRET PROSE")
    p = rs.build_project(tmp_path / "p", scenes=[rs.scene("s001")])
    rs.write_json(p / "trees" / "s001.json",
                  {"nodes": {"n1": rs.node("n1", None, "real text.")}, "head": "n1"})
    (p / "scenes.json").rename(p / "scenes_real.json")
    (p / "scenes.json").symlink_to(outside / "secret.md")
    (p / "trees" / "linked.json").symlink_to(outside / "secret.md")
    (p / "checks" / "leak.md").symlink_to(outside / "secret.md")
    res = load(p)
    blob = repr(res.snapshot) + " ".join(res.warnings)
    assert "OUTSIDE SECRET PROSE" not in blob, "linked contents are never read"
    assert "linked.json" in blob and "scenes.json" in blob
    assert res.snapshot.trees.get("linked") is None
    # real scene data survives the refused symlink
    assert res.snapshot.trees["s001"].active_text == "real text."


def test_optional_sources_recover_after_read_failure(tmp_path, load):
    p = rs.build_project(tmp_path / "p")
    (p / "bible.md").mkdir()  # unreadable as text
    res = load(p)
    assert res.snapshot.notes.bible is None
    assert any("bible.md" in w for w in res.warnings)
    (p / "bible.md").rmdir()
    rs.write_text(p / "bible.md", "RECOVERED BIBLE")
    res2 = load(p, cache=rm.SourceCache())
    assert res2.snapshot.notes.bible == "RECOVERED BIBLE"
    assert not res2.warnings


def test_secrets_and_unread_sources_never_surface(tmp_path, load, monkeypatch):
    monkeypatch.setenv("FEATHERLESS_API_KEY", "ENVSECRET-123")
    p = rs.build_project(
        tmp_path / "p",
        scenes=[rs.scene("s001")],
        trees={"s001": rs.tree({"n1": rs.node("n1", None, "One.",
                                              lorebooks="LORESECRET")}, head="n1")},
        project_extra={"api_key": "KEYSECRET", "api_key_env": "ENVSECRET-123",
                       "roles": {"writer": {"model": "secret-model"}}},
        state=None)
    rs.write_text(p / ".env", "FEATHERLESS_API_KEY=DOTENVSECRET")
    rs.write_text(p / "writer_preset.json", '{"instruct": "PRESETSECRET"}')
    rs.write_text(p / "calls.jsonl", '{"prompt": "LOGSECRET"}')
    rs.write_text(p / "outline.md", "OUTLINESECRET")
    res = load(p)
    blob = repr(res.snapshot) + " ".join(res.warnings)
    for secret in ("KEYSECRET", "ENVSECRET-123", "DOTENVSECRET", "PRESETSECRET",
                   "LOGSECRET", "OUTLINESECRET", "secret-model"):
        assert secret not in blob, f"{secret} must never surface"
    snap = res.snapshot
    assert snap.project.title == "Test Title" and snap.project.target_words == 17000
    assert snap.trees["s001"].nodes["n1"].text == "One."
