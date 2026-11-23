"""Headless tests for the Qt-independent steering save adapter.

scene_steering is the narrow write boundary for the gui shell: only the
top-level `steer` field of trees/<scene>.json, only for a scene with a card
in scenes.json, only through safe paths, and only when the exact tree source
bytes (or absence) still match the baseline captured when editing began.
"""

import json
import os
import pathlib
import subprocess
import sys

import pytest

import longform_core.scene_steering as ss
import reader_support as rs

REPO = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def proj(tmp_path):
    p = rs.build_project(tmp_path / "p", scenes=[
        rs.scene("s001", chapter=1, title="A"),
        rs.scene("s002", chapter=1, title="B"),
    ], trees={
        "s001": rs.tree({"n1": rs.node("n1", None, "one two.")}, head="n1"),
    }, bible="BIBLE", state="STATE")
    return p


def state(p, sid):
    return ss.load(p, sid)


def test_absent_tree_defaults_to_empty_and_editable(proj):
    st = state(proj, "s002")
    assert st.editable and st.text == "" and st.baseline is not None


def test_saved_steer_round_trip(tmp_path):
    p = rs.build_project(tmp_path / "p", scenes=[rs.scene("s001")],
                         trees={"s001": rs.tree(
                             {"n1": rs.node("n1", None, "t.")}, head="n1")})
    st = ss.load(p, "s001")
    out = ss.save(p, "s001", "Keep it slow.\n\nMention the tower.",
                  st.baseline)
    assert out.ok
    again = ss.load(p, "s001")
    assert again.text == "Keep it slow.\n\nMention the tower.\n\n".strip()
    assert again.text == "Keep it slow.\n\nMention the tower."
    assert again.editable


def test_clear_persists_empty(tmp_path):
    t = rs.tree({"n1": rs.node("n1", None, "t.")}, head="n1")
    t["steer"] = "old direction"
    p = rs.build_project(tmp_path / "p", scenes=[rs.scene("s001")],
                         trees={"s001": t})
    st = ss.load(p, "s001")
    assert st.text == "old direction"
    out = ss.save(p, "s001", "", st.baseline)
    assert out.ok
    assert ss.load(p, "s001").text == ""


def test_save_preserves_every_other_field(proj):
    before = json.loads((proj / "trees" / "s001.json").read_text())
    st = state(proj, "s001")
    out = ss.save(proj, "s001", "new", st.baseline)
    assert out.ok
    after = json.loads((proj / "trees" / "s001.json").read_text())
    assert after["steer"] == "new"
    for key in ("nodes", "head", "counter"):
        assert after[key] == before[key]
    assert set(after) - {"steer"} == set(before) - {"steer"}


def test_absent_tree_save_creates_default_tree_only(proj):
    files = {f.name: f.read_bytes() for f in proj.rglob("*") if f.is_file()}
    st = state(proj, "s002")
    out = ss.save(proj, "s002", "direction", st.baseline)
    assert out.ok
    d = json.loads((proj / "trees" / "s002.json").read_text())
    assert d == {"nodes": {}, "head": None, "counter": 0, "steer": "direction"}
    now_files = {f.name: f.read_bytes() for f in proj.rglob("*") if f.is_file()}
    added = set(now_files) - set(files)
    assert added == {"s002.json"}, f"only the scene's tree may be created: {added}"
    for name in files:
        if name != "s002.json":
            assert now_files[name] == files[name], name


def test_cli_reads_the_same_tree_level_steer(proj):
    st = state(proj, "s001")
    assert ss.save(proj, "s001", "cli sees this", st.baseline).ok
    import longform

    class P:
        root = proj.resolve()

        def f(self, *parts):
            return self.root.joinpath(*parts)

    tree = longform.Tree(P(), "s001")
    assert tree.d["steer"] == "cli sees this"
    assert tree.d["head"] == "n1"


def test_retained_tree_without_card_is_refused(tmp_path):
    p = rs.build_project(tmp_path / "p", scenes=[rs.scene("s001")], trees={
        "kept": rs.tree({"n1": rs.node("n1", None, "kept.")}, head="n1")})
    st = ss.load(p, "kept")
    assert not st.editable and "no card" in st.reason
    out = ss.save(p, "kept", "x", None)
    assert not out.ok
    raw = (p / "trees" / "kept.json").read_text()
    assert "kept." in raw and '"steer"' not in raw


def test_unsafe_scene_id_refused(proj):
    st = ss.load(proj, "../evil")
    assert not st.editable and st.text is None


def test_missing_card_refused(proj):
    st = ss.load(proj, "s999")
    assert not st.editable and st.text is None and "no card" in st.reason


def test_non_string_steer_refused(tmp_path):
    t = rs.tree({"n1": rs.node("n1", None, "t.")}, head="n1")
    t["steer"] = 42
    p = rs.build_project(tmp_path / "p", scenes=[rs.scene("s001")],
                         trees={"s001": t})
    st = ss.load(p, "s001")
    assert not st.editable and "not text" in st.reason


def test_damaged_tree_shapes_refused(tmp_path):
    p = rs.build_project(tmp_path / "p", scenes=[rs.scene("s001")])
    (p / "trees" / "s001.json").write_text("{broken", encoding="utf-8")
    assert "not valid JSON" in ss.load(p, "s001").reason
    rs.write_json(p / "trees" / "s001.json", ["not", "a", "dict"])
    assert "unexpected structure" in ss.load(p, "s001").reason


def test_external_tree_edit_makes_save_stale(proj):
    st = state(proj, "s001")
    # external CLI-style write after the baseline was captured
    tree = json.loads((proj / "trees" / "s001.json").read_text())
    tree["nodes"]["n2"] = rs.node("n2", "n1", "later words")
    rs.write_json(proj / "trees" / "s001.json", tree)
    out = ss.save(proj, "s001", "mine", st.baseline)
    assert not out.ok and out.stale and "changed on disk" in out.reason
    assert ss.load(proj, "s001").text == "", "external state untouched"


def test_external_scenes_card_change_makes_save_stale(proj):
    st = state(proj, "s001")
    scenes = json.loads((proj / "scenes.json").read_text())
    scenes[0]["title"] = "Renamed"
    rs.write_json(proj / "scenes.json", scenes)
    out = ss.save(proj, "s001", "mine", st.baseline)
    assert not out.ok and out.stale and "card" in out.reason


def test_absent_tree_that_appears_makes_save_stale(proj):
    st = state(proj, "s002")
    rs.write_json(proj / "trees" / "s002.json",
                  rs.tree({"n1": rs.node("n1", None, "arrived.")}, head="n1"))
    out = ss.save(proj, "s002", "mine", st.baseline)
    assert not out.ok and out.stale


def test_symlink_replacement_refused_before_write(proj, tmp_path):
    st = state(proj, "s001")
    outside = tmp_path / "outside.json"
    outside.write_text('{"nodes": {}, "head": null, "counter": 0}', encoding="utf-8")
    target = proj / "trees" / "s001.json"
    target.unlink()
    target.symlink_to(outside)
    out = ss.save(proj, "s001", "nope", st.baseline)
    assert not out.ok and "symlink" in out.reason
    assert not os.path.islink(proj / "trees" / "s001.json.tmp")


def test_io_error_refused(proj, monkeypatch):
    st = state(proj, "s001")

    import longform_core.scene_steering as ssm
    def boom(path, data):
        raise OSError("disk full")
    monkeypatch.setattr(ssm, "write_json", boom)
    out = ss.save(proj, "s001", "x", st.baseline)
    assert not out.ok and "written" in out.reason
    raw = (proj / "trees" / "s001.json").read_text()
    assert '"steer"' not in raw


def test_no_baseline_refused(proj):
    out = ss.save(proj, "s001", "x", None)
    assert not out.ok and not out.stale


def test_no_network_and_no_unrelated_changes(proj):
    files = {f.name: f.read_bytes() for f in proj.rglob("*") if f.is_file()}
    st = state(proj, "s001")
    assert ss.save(proj, "s001", "only steer", st.baseline).ok
    now = {f.name: f.read_bytes() for f in proj.rglob("*") if f.is_file()}
    changed = {n for n in files if files[n] != now.get(n)}
    assert changed == {"s001.json"}, changed


def test_scenes_json_unrelated_change_does_not_block_save(proj):
    st = state(proj, "s001")
    scenes = json.loads((proj / "scenes.json").read_text())
    scenes.append(rs.scene("s003"))
    rs.write_json(proj / "scenes.json", scenes)
    out = ss.save(proj, "s001", "still fine", st.baseline)
    assert out.ok, out.reason


def test_adapter_is_qt_and_tk_free(tmp_path):
    code = (
        "import sys, longform_core.scene_steering as ss\n"
        "assert 'PySide6' not in sys.modules and 'tkinter' not in sys.modules\n"
        "assert 'longform_core.gui' not in sys.modules\n"
        "assert 'longform_core.gui_window' not in sys.modules\n"
        "print('STEER_CLEAN')\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "STEER_CLEAN" in r.stdout
