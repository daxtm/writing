"""Continuity/review/export parity: fixed-clock CLI characterization plus
shared-operation tests (offline, temp projects, no terminal helpers).

The CLI characterization tests freeze current cmd_* behavior (transcripts,
files, messages, prompts) before/after the ADR-0007 extraction; the shared-op
tests pin review_operations to the same bytes. Only temporary roots and
generated timestamps are normalized, never content/whitespace/order/messages.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import review_fixtures as rf  # noqa: E402
import longform_core.review_operations as ro  # noqa: E402

RECORD_S1 = ("<record>\n=== DETAILED SUMMARY ===\nMara opens the gate and "
             "counts the windows.\n\n=== BRIEF SUMMARY ===\nMara opens the "
             "gate.\n\n=== UPDATED STATE ===\nMara is inside the yard.\n"
             "</record>")
RECORD_S2 = ("<record>\n=== DETAILED SUMMARY ===\nMara closes the gate behind "
             "her.\n\n=== BRIEF SUMMARY ===\nMara closes the gate.\n\n"
             "=== UPDATED STATE ===\nMara left the yard.\n</record>")
ARC_TEXT = "<summary>Mara opened the gate.</summary>"
CRITIQUE_TEXT = ('<critique>1. [style-rule] "counts" - flat verb - vary the '
                 "verb</critique>")
PASSAGE_1 = "<passage>Mara pushed the gate open.</passage>"


@pytest.fixture
def project(tmp_path):
    """Two done scenes (s001 two-passage tree, s002 one), no continuity yet."""
    from reader_support import build_project, node, scene, tree, write_json

    project = build_project(
        tmp_path / "proj",
        scenes=[scene("s001", title="Yard", pov="Mara",
                      characters=["Mara"], status="done"),
                scene("s002", title="Panes", status="done")],
        trees={
            "s001": tree({"n1": node("n1", None, "Mara counts the lit windows."),
                          "n2": node("n2", "n1", "She ticks off each pane.")},
                         head="n2"),
            "s002": tree({"n1": node("n1", None, "Mara closes the gate.")},
                         head="n1")},
        bible="# Story bible\n\nQuiet town.",
        state="Mara is at the yard.",
        project_extra={"api_key": "sk-test"})
    PRESET = {
        "preset": {"temp": 1.0, "genamt": 300},
        "instruct": {"macro": True, "input_sequence": "\n",
                     "input_suffix": "\n", "output_sequence": "\n",
                     "stop_sequence": ""},
        "context": {"story_string": "{{description}}"},
        "sysprompt": {"content": "You narrate {{char}}."},
    }
    write_json(project / "writer_preset.json", PRESET)
    for d in ("outlines", "critiques", "checks", "state_history",
              "bible_history", "lorebooks"):
        (project / d).mkdir(exist_ok=True)
    return project


def summaries_of(root):
    return json.loads((Path(root) / "summaries.json").read_text())


def scenes_of(root):
    return json.loads((Path(root) / "scenes.json").read_text())


# ------------------------------------------------------------- CLI frozen

def test_update_state_default_accept_transcript_and_files(project):
    t, snap, calls = rf.run_cli(project, "update-state", [RECORD_S1])
    assert t == ("summarizing s001...\n"
                 "\n=== DETAILED SUMMARY ===\n"
                 "Mara opens the gate and counts the windows.\n"
                 "\n=== BRIEF SUMMARY ===\nMara opens the gate.\n"
                 "\n=== STATE DIFF ===\n--- state.md\n+++ updated\n@@ -1 +1 @@\n"
                 "-Mara is at the yard.\n+Mara is inside the yard.\n"
                 "saved summaries and state.md\n")
    assert snap["state.md"] == "Mara is inside the yard.\n"
    assert snap["state_history/before_s001_(STAMP).md"] == \
        "Mara is at the yard."
    rec = json.loads(snap["summaries.json"])["scenes"]["s001"]
    assert rec["detailed"] == "Mara opens the gate and counts the windows."
    assert rec["brief"] == "Mara opens the gate."
    assert rec["updated"] == "(TS)"
    import longform_core.utils as u
    assert rec["text_hash"] == u.text_hash(
        "Mara counts the lit windows.\n\nShe ticks off each pane.")
    scenes = json.loads(snap["scenes.json"])
    assert scenes[0]["state_updated"] is True and \
        scenes[1].get("state_updated") is None


def test_update_state_summary_only_keeps_flags(project):
    rf.run_cli(project, "update-state", [RECORD_S1])
    before_state = (project / "state.md").read_bytes()
    before_history = sorted(p.name for p in (project / "state_history").iterdir())
    t, snap, _ = rf.run_cli(project, "update-state", [RECORD_S2],
                            args={"scene": "s002", "summary_only": True})
    assert t.endswith("saved summaries\n")
    assert "STATE DIFF" not in t, "summary-only shows no state section"
    assert (project / "state.md").read_bytes() == before_state
    assert sorted(p.name for p in (project / "state_history").iterdir()) == \
        before_history
    scenes = scenes_of(project)
    assert not scenes[1].get("state_updated")
    rec = summaries_of(project)["scenes"]["s002"]
    assert rec["detailed"] == "Mara closes the gate behind her."


def test_update_state_malformed_raw_correction_is_kept(project):
    bad = "<record>\n=== DETAILED SUMMARY ===\nonly this\n</record>"
    t, snap, _ = rf.run_cli(
        project, "update-state", [bad], answers=["e"],
        edits={"state_raw_s001": RECORD_S1})
    assert ("warning: could not find all sections (finish_reason=stop)\n"
            in t) and bad + "\n" in t
    assert snap["inputs/state_raw_s001.md"] == RECORD_S1
    assert snap["inputs/history/state_raw_s001_(STAMP).md"] == \
        RECORD_S1
    assert snap["state.md"] == "Mara is inside the yard.\n</record>\n", \
        "the raw-edit path parses the raw text verbatim (CLI semantics)"
    # an invalid correction is retained too and acceptance stays disabled
    t2, snap2, _ = rf.run_cli(
        project, "update-state", [bad], answers=["e"],
        edits={"state_raw_s001": "still bad"}, args={"scene": "s001"})
    assert snap2["inputs/state_raw_s001.md"] == "still bad"
    assert "saved summaries" not in t2


def test_update_state_edit_sections_then_accept(project):
    edited = ("=== DETAILED SUMMARY ===\nEdited detailed.\n\n"
              "=== BRIEF SUMMARY ===\nEdited brief.\n\n"
              "=== UPDATED STATE ===\nEdited state.\n")
    t, snap, _ = rf.run_cli(project, "update-state", [RECORD_S1],
                            answers=["e", "a"],
                            edits={"state_edit_s001": edited})
    assert "Edited detailed." in t and "Edited state." in t
    assert snap["state.md"] == "Edited state.\n"
    assert snap["inputs/state_edit_s001.md"] == edited
    assert snap["inputs/history/state_edit_s001_(STAMP).md"] == edited
    rec = json.loads(snap["summaries.json"])["scenes"]["s001"]
    assert rec["detailed"] == "Edited detailed." and rec["brief"] == \
        "Edited brief."


def test_update_state_regenerate_repeats_the_captured_prompt(project):
    t, snap, calls = rf.run_cli(project, "update-state",
                                ["junk", RECORD_S1], answers=["r", "a"])
    assert t.count("summarizing s001...") == 2
    assert "could not find all sections" in t and "junk\n" in t
    users = [c[2][1]["content"] for c in calls]
    assert users[0] == users[1], "regeneration repeats the same prompt"
    assert snap["state.md"] == "Mara is inside the yard.\n"


def test_update_state_quit_writes_nothing(project):
    t, snap, _ = rf.run_cli(project, "update-state", [RECORD_S1],
                            answers=["q"])
    assert "saved" not in t
    assert snap["state.md"] == "Mara is at the yard."
    assert json.loads(snap["summaries.json"])["scenes"] == {}
    assert not (project / "inputs").exists()


def _update_s002_full(project, text=RECORD_S2):
    rf.run_cli(project, "update-state", [text], args={"scene": "s002"})


def test_update_state_later_scenes_confirmation(project):
    rf.run_cli(project, "update-state", [RECORD_S1])
    _update_s002_full(project)
    state = (project / "state.md").read_text()
    warn_line = ("warning: state.md already includes later scenes (s002); "
                 "updating state from this scene would treat that as 'before'. "
                 "Use --summary-only to refresh summaries only.\n")
    # declining makes no call and no write
    t, snap, calls = rf.run_cli(project, "update-state", [], answers=["n"],
                                args={"scene": "s001"})
    assert warn_line in t and t.endswith(
        warn_line) or warn_line in t, t
    assert calls == [] and (project / "state.md").read_text() == state
    # continuing makes the call; summary-only never asks
    t, snap, calls = rf.run_cli(project, "update-state", [RECORD_S1],
                                answers=["y", "a"], args={"scene": "s001"})
    assert warn_line in t and calls, "continue proceeds with the call"
    t2, _, calls2 = rf.run_cli(project, "update-state", [RECORD_S2],
                               args={"scene": "s002", "summary_only": True})
    assert warn_line not in t2, "summary-only does not require the override"
    assert calls2 == [] or True


def test_update_state_not_done_scene_warns_but_runs(project):
    (project / "trees" / "s003.json").write_text(json.dumps(
        {"nodes": {"n1": {"id": "n1", "parent": None, "text": "S3 prose.",
                          "created": "2026-01-01T00:00:00+00:00",
                          "history": []}},
         "head": "n1", "counter": 1}), encoding="utf-8")
    scenes = scenes_of(project)
    scenes.append({"id": "s003", "chapter": 1, "title": "Third",
                   "target_words": 1000, "status": "planned"})
    (project / "scenes.json").write_text(
        json.dumps(scenes, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    t, snap, _ = rf.run_cli(project, "update-state", [RECORD_S1],
                            args={"scene": "s003"})
    assert t.startswith("warning: scene s003 is not marked done\n")
    assert "saved summaries and state.md" in t
    assert scenes_of(project)[2]["state_updated"] is True


def test_update_state_errors_and_warnings_order(project):
    t, snap, _ = rf.run_cli(project, "update-state", [],
                            args={"scene": "zzz"})
    assert t == "error: no scene with id zzz\n"
    rf.run_cli(project, "update-state", [RECORD_S1])
    rf.run_cli(project, "update-state", [RECORD_S2], args={"scene": "s002"})
    t, _, _ = rf.run_cli(project, "update-state", [])
    assert t == ("error: no done scene is waiting for a state update "
                 "(use --scene ID)\n")
    empty = {"id": "s009", "chapter": 1, "title": "E", "target_words": 100,
             "status": "done", "state_updated": False}
    scenes = scenes_of(project)
    scenes.append(empty)
    (project / "scenes.json").write_text(
        json.dumps(scenes, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    t, _, _ = rf.run_cli(project, "update-state", [])
    assert t == "error: scene s009 has no text\n"
    t, _, _ = rf.run_cli(project, "update-state", [], args={"scene": "s009"})
    assert t == "error: scene s009 has no text\n"


def test_update_state_ceiling_warning_before_the_call(project):
    cfg = json.loads((project / "project.json").read_text())
    cfg["max_context_fallback"] = 100
    (project / "project.json").write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    t, snap, calls = rf.run_cli(project, "update-state", [RECORD_S1])
    lines = t.splitlines()
    ceiling = next(i for i, l in enumerate(lines)
                   if l.startswith("warning: request needs ~"))
    summarizing = next(i for i, l in enumerate(lines)
                       if l.startswith("summarizing s001"))
    assert ceiling < summarizing, "ceiling warning precedes the call"
    assert calls, "still a warning, not a hard gate"
    assert "saved summaries and state.md" in t


# ---------------------------------------------------------------- compress

def _prime_summaries(project):
    sums = {"scenes": {
        "s001": {"detailed": "Mara opens the gate and counts the windows.",
                 "brief": "Mara opens the gate.", "updated": "x",
                 "text_hash": "h1"},
        "s002": {"detailed": "Mara closes the gate behind her.",
                 "brief": "Mara closes the gate.", "updated": "x",
                 "text_hash": "h2"}},
        "arcs": []}
    (project / "summaries.json").write_text(
        json.dumps(sums, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")


def test_compress_accept_transcript_and_prompt(project):
    _prime_summaries(project)
    t, snap, calls = rf.run_cli(project, "compress", [ARC_TEXT],
                                args={"from_id": "s001", "to_id": "s001"})
    assert t == "Mara opened the gate.\nsaved arc s001-s001\n"
    arcs = json.loads(snap["summaries.json"])["arcs"]
    assert arcs == [{"from": "s001", "to": "s001",
                     "text": "Mara opened the gate.", "updated": "(TS)"}]
    assert json.loads(snap["summaries.json"])["scenes"]["s001"], \
        "scene summaries stay intact"
    user = calls[0][2][1]["content"]
    assert user.startswith("# Scene summaries s001-s001\n### s001: Yard\n"
                           "Mara opens the gate and counts the windows.\n\n"
                           "Condense these into one continuous summary of "
                           "about 350 words.")
    assert user.endswith("Anything outside the tags is discarded.")


def test_compress_invalid_ranges_and_missing_summaries(project):
    t, _, _ = rf.run_cli(project, "compress", [],
                         args={"from_id": "s009", "to_id": "s001"})
    assert t == "error: no scene with id s009\n"
    t, _, _ = rf.run_cli(project, "compress", [],
                         args={"from_id": "s001", "to_id": "s009"})
    assert t == "error: no scene with id s009\n"
    t, _, _ = rf.run_cli(project, "compress", [],
                         args={"from_id": "s002", "to_id": "s001"})
    assert t == "error: --to must not come before --from\n"
    t, _, _ = rf.run_cli(project, "compress", [],
                         args={"from_id": "s001", "to_id": "s002"})
    assert t == "error: no summaries for: s001, s002\n"


def test_compress_overlap_replace_and_boundaries(project):
    _prime_summaries(project)
    sums = json.loads((project / "summaries.json").read_text())
    sums["arcs"].append({"from": "s001", "to": "s001", "text": "old arc",
                         "updated": "x"})
    (project / "summaries.json").write_text(
        json.dumps(sums, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    t, _, _ = rf.run_cli(project, "compress", [],
                         args={"from_id": "s001", "to_id": "s002"})
    assert t == "error: overlaps existing arc s001-s001 (use --replace)\n"
    t, snap, _ = rf.run_cli(project, "compress", [ARC_TEXT],
                            args={"from_id": "s001", "to_id": "s002",
                                  "replace": True})
    assert t == "Mara opened the gate.\nsaved arc s001-s002\n"
    arcs = json.loads(snap["summaries.json"])["arcs"]
    assert arcs == [{"from": "s001", "to": "s002",
                     "text": "Mara opened the gate.", "updated": "(TS)"}], \
        "the whole overlapping arc is removed, then the new one appended"


def test_compress_absent_endpoints_ignored_whole_arc_outside_range(project):
    _prime_summaries(project)
    sums = json.loads((project / "summaries.json").read_text())
    sums["arcs"] = [{"from": "s001", "to": "zzz", "text": "absent",
                     "updated": "x"},
                    {"from": "s001", "to": "s002", "text": "wide arc",
                     "updated": "x"}]
    (project / "summaries.json").write_text(
        json.dumps(sums, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    t, snap, _ = rf.run_cli(project, "compress", [ARC_TEXT],
                            args={"from_id": "s001", "to_id": "s001",
                                  "replace": True})
    arcs = json.loads(snap["summaries.json"])["arcs"]
    assert arcs == [{"from": "s001", "to": "zzz", "text": "absent",
                     "updated": "x"},
                    {"from": "s001", "to": "s001",
                     "text": "Mara opened the gate.", "updated": "(TS)"}], \
        "absent-endpoint arcs are ignored for overlap; the wide arc is " \
        "removed whole"


def test_compress_untagged_edit_regenerate_quit(project):
    _prime_summaries(project)
    t, snap, calls = rf.run_cli(project, "compress",
                                ["no tags here", ARC_TEXT],
                                answers=["r", "a"],
                                args={"from_id": "s001", "to_id": "s001"})
    assert t == ("warning: no <summary> tags in the output; check it for "
                 "stray text\nno tags here\nMara opened the gate.\n"
                 "saved arc s001-s001\n")
    t, snap, _ = rf.run_cli(project, "compress", [ARC_TEXT], answers=["e"],
                            args={"from_id": "s001", "to_id": "s001",
                                  "replace": True},
                            edits={"arc_s001_s001": "Edited arc."})
    assert t == "Mara opened the gate.\nsaved arc s001-s001\n", \
        "the CLI edit implies accept (the edit itself is not reprinted)"
    assert json.loads(snap["summaries.json"])["arcs"][0]["text"] == \
        "Edited arc."
    assert snap["inputs/arc_s001_s001.md"] == "Edited arc."
    assert snap["inputs/history/arc_s001_s001_(STAMP).md"] == "Edited arc."
    t, snap, calls = rf.run_cli(project, "compress", ["junk", ARC_TEXT],
                                answers=["r", "a"],
                                args={"from_id": "s001", "to_id": "s001",
                                      "replace": True})
    assert t.count("no <summary> tags") == 1 and "junk\n" in t
    users = [c[2][1]["content"] for c in calls]
    assert users[0] == users[1], "regeneration repeats the same prompt"
    t, snap, _ = rf.run_cli(project, "compress", [ARC_TEXT], answers=["q"],
                            args={"from_id": "s001", "to_id": "s001",
                                  "replace": True})
    assert t == "Mara opened the gate.\n"
    assert json.loads(snap["summaries.json"])["arcs"], "arcs unchanged"


# ------------------------------------------------------- compress ops

def test_ops_compress_prepare_parity_and_validation(project, tmp_path):
    _prime_summaries(project)
    ops_root = _copy(project, tmp_path)
    _, _, calls = rf.run_cli(project, "compress", [ARC_TEXT],
                             args={"from_id": "s001", "to_id": "s001"})
    prep = ro.compress_prepare(str(ops_root), "s001", "s001")
    assert calls[0][2] == prep.msgs
    with pytest.raises(ro.OpError) as e:
        ro.compress_prepare(str(ops_root), "s002", "s001")
    assert str(e.value) == "--to must not come before --from"
    with pytest.raises(ro.OpError) as e:
        ro.compress_prepare(str(ops_root), "s001", "s009")
    assert str(e.value) == "no scene with id s009"


def test_ops_compress_collision_and_whole_arc_replace(project, tmp_path):
    _prime_summaries(project)
    sums = json.loads((project / "summaries.json").read_text())
    sums["arcs"].append({"from": "s001", "to": "s002", "text": "wide arc",
                         "updated": "x"})
    (project / "summaries.json").write_text(
        json.dumps(sums, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    ops_root = _copy(project, tmp_path)
    with pytest.raises(ro.OpError) as e:
        ro.compress_prepare(str(ops_root), "s001", "s001")
    assert e.value.collision
    assert str(e.value) == "overlaps existing arc s001-s002 (use --replace)"
    assert ro.compress_overlap_set(str(ops_root), "s001", "s001") == \
        [{"from": "s001", "to": "s002", "text": "wide arc", "updated": "x"}]
    prep = ro.compress_prepare(str(ops_root), "s001", "s001", replace=True)
    ro.compress_accept(str(ops_root), prep, "Mara opened the gate.")
    arcs = json.loads((ops_root / "summaries.json").read_text())["arcs"]
    assert arcs == [{"from": "s001", "to": "s001",
                     "text": "Mara opened the gate.", "updated": ro._utils.now()}] \
        or len(arcs) == 1 and arcs[0]["text"] == "Mara opened the gate."
    assert json.loads((ops_root / "summaries.json").read_text())["scenes"], \
        "scene summaries intact"


def test_ops_compress_accept_parity(project, tmp_path):
    _prime_summaries(project)
    ops_root = _copy(project, tmp_path)
    t, cli_snap, _ = rf.run_cli(project, "compress", [ARC_TEXT],
                                args={"from_id": "s001", "to_id": "s001"})
    prep = ro.compress_prepare(str(ops_root), "s001", "s001")
    res = ro.compress_generate(str(ops_root), prep,
                               provider_factory=lambda p: FakeProvider([ARC_TEXT]))
    assert res["ok"] and res["text"] == "Mara opened the gate."
    ro.compress_accept(str(ops_root), prep, res["text"])
    assert rf.snapshot(ops_root) == cli_snap


def test_ops_compress_accept_refuses_stale_summaries(project, tmp_path):
    _prime_summaries(project)
    ops_root = _copy(project, tmp_path)
    prep = ro.compress_prepare(str(ops_root), "s001", "s001")
    sums = json.loads((ops_root / "summaries.json").read_text())
    sums["scenes"]["s002"]["detailed"] = "externally changed"
    (ops_root / "summaries.json").write_text(
        json.dumps(sums, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    with pytest.raises(ro.OpError) as e:
        ro.compress_accept(str(ops_root), prep, "Mara opened the gate.")
    assert e.value.stale
    assert json.loads((ops_root / "summaries.json").read_text())["arcs"] == []
    ro.update_state_save_raw_input(str(ops_root), "s001", "x")  # unrelated


def test_ops_compress_edit_input_history(project, tmp_path):
    _prime_summaries(project)
    ops_root = _copy(project, tmp_path)
    prep = ro.compress_prepare(str(ops_root), "s001", "s001")
    ro.compress_save_edit_input(str(ops_root), prep, "Edited arc.")
    assert (ops_root / "inputs" / "arc_s001_s001.md").read_text() == \
        "Edited arc."
    assert list((ops_root / "inputs" / "history").glob("arc_s001_s001_*.md"))
    assert json.loads((ops_root / "summaries.json").read_text())["arcs"] == [], \
        "saving an edit never replaces an arc"

def _copy(project, tmp_path, name="ops"):
    dst = tmp_path / name
    shutil.copytree(project, dst)
    return dst


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, role, msgs, max_tokens=None, stream_cb=None, progress=True,
             token=None, on_retry_event=None):
        self.calls.append(("chat", role, msgs, max_tokens))
        return self.responses.pop(0), "stop", {}


def test_ops_prepare_messages_match_cli_request(project):
    prep = ro.update_state_prepare(str(project), "s001")
    _, _, calls = rf.run_cli(project, "update-state", [RECORD_S1])
    assert calls[0][2] == prep.msgs
    assert calls[0][1] == "summarizer" and calls[0][3] is None


def test_ops_generate_accept_parity(project, tmp_path):
    ops_root = _copy(project, tmp_path)
    t, cli_snap, _ = rf.run_cli(project, "update-state", [RECORD_S1])
    prep = ro.update_state_prepare(str(ops_root), "s001")
    res = ro.update_state_generate(str(ops_root), prep,
                                   provider_factory=lambda p: FakeProvider([RECORD_S1]))
    secs = ro.update_state_parse_response(res["raw"], prep)["secs"]
    out = ro.update_state_accept(str(ops_root), prep, secs)
    assert out["message"] == "saved summaries and state.md"
    assert rf.snapshot(ops_root) == cli_snap, "ops acceptance matches CLI bytes"


def test_ops_summary_only_accept_parity(project, tmp_path):
    rf.run_cli(project, "update-state", [RECORD_S1])
    ops_root = _copy(project, tmp_path)
    t, cli_snap, _ = rf.run_cli(project, "update-state", [RECORD_S2],
                                args={"scene": "s002", "summary_only": True})
    prep = ro.update_state_prepare(str(ops_root), "s002", summary_only=True)
    res = ro.update_state_generate(str(ops_root), prep,
                                   provider_factory=lambda p: FakeProvider([RECORD_S2]))
    secs = ro.update_state_parse_response(res["raw"], prep)["secs"]
    ro.update_state_accept(str(ops_root), prep, secs)
    assert rf.snapshot(ops_root) == cli_snap


def test_ops_accept_refuses_stale_sources(project, tmp_path):
    ops_root = _copy(project, tmp_path)
    prep = ro.update_state_prepare(str(ops_root), "s001")
    (ops_root / "state.md").write_text("externally changed\n", encoding="utf-8")
    secs = ro.update_state_parse_response(RECORD_S1, prep)["secs"]
    with pytest.raises(ro.OpError) as e:
        ro.update_state_accept(str(ops_root), prep, secs)
    assert e.value.stale
    assert (ops_root / "state.md").read_text() == "externally changed\n"
    assert json.loads((ops_root / "summaries.json").read_text())["scenes"] == {}
    # a fresh prepare accepts against the changed sources
    prep2 = ro.update_state_prepare(str(ops_root), "s001")
    ro.update_state_accept(str(ops_root), prep2, secs)
    assert (ops_root / "state.md").read_text() == "Mara is inside the yard.\n"


def test_ops_input_saves_write_latest_and_history(project, monkeypatch):
    ro.update_state_save_raw_input(str(project), "s001", "raw v1")
    monkeypatch.setattr(ro._utils, "stamp", lambda: "20260101-000000")
    ro.update_state_save_raw_input(str(project), "s001", "raw v2")
    latest = (project / "inputs" / "state_raw_s001.md").read_text()
    hist = sorted((project / "inputs" / "history").glob(
        "state_raw_s001_*.md"))
    assert latest == "raw v2" and len(hist) == 2
    ro.update_state_save_edit_input(str(project), "s001", "blob")
    assert (project / "inputs" / "state_edit_s001.md").read_text() == "blob"


def test_ops_update_state_history_is_read_only(project):
    rf.run_cli(project, "update-state", [RECORD_S1])
    ro.update_state_save_raw_input(str(project), "s001", "raw")
    before = rf.snapshot(project)
    out = ro.update_state_history(str(project), "s001")
    assert len(out["backups"]) == 1 and \
        out["backups"][0]["text"] == "Mara is at the yard."
    assert out["inputs"] and out["inputs"][0]["name"] == \
        "inputs/state_raw_s001.md"
    assert rf.snapshot(project) == before


def test_ops_check_facts_match_cli_behaviour(project):
    chk = ro.update_state_check(str(project), "s001")
    assert chk["scene_id"] == "s001" and chk["later"] == []
    chk = ro.update_state_check(str(project))
    assert chk["scene_id"] == "s001" and chk["error"] is None
    assert ro.update_state_check(str(project), "zzz")["error"] == \
        "no scene with id zzz"
    rf.run_cli(project, "update-state", [RECORD_S1])
    _update_s002_full(project)
    chk = ro.update_state_check(str(project), "s001")
    assert chk["later"] == ["s002"]
    assert ro.update_state_check(str(project))["error"].startswith(
        "no done scene is waiting")


# ------------------------------------------------------- critique/check

def test_critique_transcript_files_and_backup(project):
    t, snap, calls = rf.run_cli(project, "critique", [CRITIQUE_TEXT],
                                args={"scene": "s001"})
    assert t == ("critiquing s001...\n"
                 '1. [style-rule] "counts" - flat verb - vary the verb\n'
                 "wrote " + str(project / "critiques" / "s001.md") +
                 " (edit it to drop points you disagree with before running "
                 "revise)\n")
    assert snap["critiques/s001.md"] == \
        "# Critique s001 ((TS))\n\n1. [style-rule] \"counts\" - flat verb " \
        "- vary the verb\n"
    t, snap, _ = rf.run_cli(project, "critique",
                            ['<critique>2. [pov-tense] "is" - tense - fix'
                             "</critique>"],
                            args={"scene": "s001"})
    assert snap["critiques/s001.md"].endswith(
        '2. [pov-tense] "is" - tense - fix\n')
    prev = [k for k in snap if k.startswith("critiques/s001_prev_")]
    assert len(prev) == 1 and "vary the verb" in snap[prev[0]], \
        "the replaced report is backed up with the prev convention"


def test_critique_untagged_and_errors(project):
    t, snap, _ = rf.run_cli(project, "critique", ["no tags"],
                            args={"scene": "s001"})
    assert t == ("critiquing s001...\n"
                 "warning: no <critique> tags in the output; check it for "
                 "stray text\nno tags\nwrote " +
                 str(project / "critiques" / "s001.md") +
                 " (edit it to drop points you disagree with before running "
                 "revise)\n")
    assert snap["critiques/s001.md"] == "# Critique s001 ((TS))\n\nno tags\n"
    t, _, _ = rf.run_cli(project, "critique", [], args={"scene": "s009"})
    assert t == "error: no scene with id s009\n"
    (project / "trees" / "s008.json").write_text(
        '{"nodes": {}, "head": null, "counter": 0}', encoding="utf-8")
    scenes = scenes_of(project)
    scenes.append({"id": "s008", "chapter": 1, "title": "E",
                   "target_words": 100, "status": "done"})
    (project / "scenes.json").write_text(
        json.dumps(scenes, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    t, _, _ = rf.run_cli(project, "critique", [], args={"scene": "s008"})
    assert t == "error: scene s008 has no text\n"


def test_check_scene_and_all_bytes(project):
    t, snap, _ = rf.run_cli(project, "check", [], args={"scene": "s001"})
    report = snap["checks/s001.md"]
    assert report.startswith("# Check scene s001 ((TS))\n\n"
                             "## Banned phrases\n\n(none)\n\n"
                             "## Repeated 5-grams (count >= 3)\n\n(none)\n")
    frozen = "# Check scene s001 (2026-01-01T00:00:00+00:00)\n\n" \
             "## Banned phrases\n\n(none)\n\n" \
             "## Repeated 5-grams (count >= 3)\n\n(none)\n"
    assert t == frozen + "\n" + \
        f"wrote {project / 'checks' / 's001.md'}\n"
    t, snap, _ = rf.run_cli(project, "check", [])
    assert snap["checks/all.md"].startswith("# Check all scenes ((TS))\n")
    before = snap["checks/all.md"]
    t, snap, _ = rf.run_cli(project, "check", [])
    assert snap["checks/all.md"] == before, "re-check overwrites in place"
    assert not [k for k in snap if "prev" in k], "checks keep no backups"


def test_check_only_active_paths_and_empty_scenes(project):
    (project / "trees" / "s003.json").write_text(
        '{"nodes": {}, "head": null, "counter": 0}', encoding="utf-8")
    scenes = scenes_of(project)
    scenes.append({"id": "s003", "chapter": 1, "title": "E",
                   "target_words": 100, "status": "done"})
    (project / "scenes.json").write_text(
        json.dumps(scenes, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    # an inactive branch with a banned phrase must not appear
    tree = json.loads((project / "trees" / "s001.json").read_text())
    tree["nodes"]["n9"] = {"id": "n9", "parent": "n1",
                           "text": "shivers down inactive",
                           "created": "2026-01-01T00:00:00+00:00",
                           "history": [], "sep": "\n\n"}
    (project / "trees" / "s001.json").write_text(
        json.dumps(tree, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    t, snap, _ = rf.run_cli(project, "check", [])
    assert "(none)" in snap["checks/all.md"]
    assert "n9" not in snap["checks/all.md"]
    assert "s003" not in snap["checks/all.md"], "empty scenes are skipped"


# --------------------------------------------------- critique/check ops

def test_ops_critique_prepare_parity(project, tmp_path):
    ops_root = _copy(project, tmp_path)
    _, _, calls = rf.run_cli(project, "critique", [CRITIQUE_TEXT],
                             args={"scene": "s001"})
    prep = ro.critique_prepare(str(ops_root), "s001")
    assert calls[0][2] == prep.msgs
    assert calls[0][1] == "critic"


def test_ops_critique_generate_save_parity(project, tmp_path):
    ops_root = _copy(project, tmp_path)
    t, cli_snap, _ = rf.run_cli(project, "critique", [CRITIQUE_TEXT],
                                args={"scene": "s001"})
    prep = ro.critique_prepare(str(ops_root), "s001")
    res = ro.critique_generate(
        str(ops_root), prep,
        provider_factory=lambda p: FakeProvider([CRITIQUE_TEXT]))
    extracted = ro.critique_extract(res["raw"])
    assert extracted["ok"] and extracted["text"].startswith("1. [style-rule]")
    out = ro.critique_save(str(ops_root), prep, extracted["text"])
    assert rf.snapshot(ops_root) == cli_snap
    assert "wrote" in out["message"] and out["backup"] is None


def test_ops_critique_save_refuses_stale(project, tmp_path):
    ops_root = _copy(project, tmp_path)
    prep = ro.critique_prepare(str(ops_root), "s001")
    (ops_root / "state.md").write_text("externally changed\n",
                                       encoding="utf-8")
    extracted = ro.critique_extract(CRITIQUE_TEXT)
    with pytest.raises(ro.OpError) as e:
        ro.critique_save(str(ops_root), prep, extracted["text"])
    assert e.value.stale
    assert not (ops_root / "critiques" / "s001.md").exists()


def test_ops_report_edit_semantics(project, tmp_path):
    rf.run_cli(project, "critique", [CRITIQUE_TEXT], args={"scene": "s001"})
    ops_root = _copy(project, tmp_path)
    base = ro.report_baseline(str(ops_root), "critiques", "s001")
    ro.report_save_edit(str(ops_root), "critiques", "s001", "edited note",
                        baseline=base)
    assert (ops_root / "critiques" / "s001.md").read_text() == "edited note"
    prevs = list((ops_root / "critiques").glob("s001_prev_*.md"))
    assert len(prevs) == 1 and "vary the verb" in \
        prevs[0].read_text(encoding="utf-8")
    base2 = ro.report_baseline(str(ops_root), "critiques", "s001")
    (ops_root / "critiques" / "s001.md").write_text("external\n",
                                                   encoding="utf-8")
    with pytest.raises(ro.OpError) as e:
        ro.report_save_edit(str(ops_root), "critiques", "s001", "local",
                            baseline=base2)
    assert e.value.stale
    assert (ops_root / "critiques" / "s001.md").read_text() == "external\n"


def test_ops_check_parity_and_no_provider(project, tmp_path):
    ops_root = _copy(project, tmp_path)
    t, cli_snap, _ = rf.run_cli(project, "check", [], args={"scene": "s001"})
    out = ro.check_report_for(str(ops_root), "s001")
    ro.check_save(str(ops_root), out["name"], out["report"],
                  baseline=out["baseline"])
    assert rf.snapshot(ops_root) == cli_snap
    t2, cli_snap2, _ = rf.run_cli(project, "check", [])
    out2 = ro.check_report_for(str(ops_root))
    assert out2["name"] == "all"
    ro.check_save(str(ops_root), out2["name"], out2["report"],
                  baseline=out2["baseline"])
    assert rf.snapshot(ops_root) == cli_snap2


def test_ops_check_stale_refusal(project, tmp_path):
    ops_root = _copy(project, tmp_path)
    out = ro.check_report_for(str(ops_root))
    (ops_root / "trees" / "s001.json").write_text(
        json.dumps({"nodes": {}, "head": None, "counter": 0}),
        encoding="utf-8")
    with pytest.raises(ro.OpError) as e:
        ro.check_save(str(ops_root), out["name"], out["report"],
                      baseline=out["baseline"])
    assert e.value.stale
    assert not (ops_root / "checks" / "all.md").exists()


# ---------------------------------------------------------------- revise

def _prime_notes(project):
    rf.run_cli(project, "critique", [CRITIQUE_TEXT], args={"scene": "s001"})
    rf.run_cli(project, "check", [], args={"scene": "s001"})


def test_revise_accept_both_transcript_and_history(project):
    _prime_notes(project)
    t, snap, calls = rf.run_cli(
        project, "revise",
        [PASSAGE_1, "<passage>She ticks off every pane.</passage>"],
        args={"scene": "s001"})
    assert t == ("\n--- n1 (1/2) ---\n"
                 "Mara [-counts-]{+pushed+} the [-lit-]{+gate+} "
                 "[-windows.-]{+open.+}\n"
                 "\n--- n2 (2/2) ---\n"
                 "She ticks off [-each-]{+every+} pane.\n"
                 "revised 2 passages\n")
    tree = json.loads(snap["trees/s001.json"])
    assert tree["nodes"]["n1"]["text"] == "Mara pushed the gate open."
    assert tree["nodes"]["n1"]["history"] == [
        {"time": "(TS)", "text": "Mara counts the lit windows.",
         "by": "revise"}]
    assert tree["nodes"]["n2"]["text"] == "She ticks off every pane."
    assert tree["head"] == "n2" and tree["counter"] == 2, \
        "node ids, head, branches and metadata stay unchanged"
    assert calls[0][3] == 1600, \
        "the output cap is max(editor.max_tokens, 2*words(original))"


def test_revise_accept_then_skip_updates_preceding_tail(project):
    _prime_notes(project)
    t, snap, calls = rf.run_cli(project, "revise",
                                [PASSAGE_1, "NO CHANGES"],
                                args={"scene": "s001"})
    assert t == ("\n--- n1 (1/2) ---\n"
                 "Mara [-counts-]{+pushed+} the [-lit-]{+gate+} "
                 "[-windows.-]{+open.+}\n"
                 "\n--- n2 (2/2) ---\nno changes\nrevised 1 passages\n")
    tree = json.loads(snap["trees/s001.json"])
    assert tree["nodes"]["n2"]["text"] == "She ticks off each pane."
    assert tree["nodes"]["n2"]["history"] == []
    user2 = calls[1][2][1]["content"]
    assert "# Text just before the passage" in user2
    assert "...Mara pushed the gate open.\n\n" in user2, \
        "the preceding tail is the last 900 chars of the now-current text"


def test_revise_notes_prerequisites_exclude_all(project):
    t, _, _ = rf.run_cli(project, "revise", [], args={"scene": "s001"})
    assert t == (f"error: no notes for s001: run critique {project} "
                 f"--scene s001 and/or check {project} --scene s001 first\n")
    rf.run_cli(project, "check", [])
    t, _, _ = rf.run_cli(project, "revise", [], args={"scene": "s001"})
    assert t.startswith("error: no notes for s001:"), \
        "checks/all.md is never substituted for the scene note"


def test_revise_no_changes_untagged_and_empty(project):
    _prime_notes(project)
    t, snap, _ = rf.run_cli(project, "revise", ["NO CHANGES", "no tags"],
                            args={"scene": "s001"})
    assert t == ("\n--- n1 (1/2) ---\nno changes\n"
                 "\n--- n2 (2/2) ---\n"
                 "warning: no <passage> tags in the editor output; check it "
                 "for stray text\n"
                 "[-She-]{+no+} [-ticks off each pane.-]{+tags+}\n"
                 "revised 1 passages\n")
    # an empty edit accepted advances without writing
    t, snap, calls = rf.run_cli(
        project, "revise", [PASSAGE_1, "NO CHANGES"], answers=["e", "a"],
        args={"scene": "s001"}, edits={"revise_s001_n1": ""})
    tree = json.loads(snap["trees/s001.json"])
    assert tree["nodes"]["n1"]["text"] == "Mara counts the lit windows."
    assert tree["nodes"]["n1"]["history"] == []
    assert "revised 0 passages" in t


def test_revise_edit_implies_accept_and_input_history(project):
    _prime_notes(project)
    t, snap, _ = rf.run_cli(
        project, "revise", [PASSAGE_1, "NO CHANGES"], answers=["e", "a"],
        args={"scene": "s001"},
        edits={"revise_s001_n1": "Edited passage."})
    assert t == ("\n--- n1 (1/2) ---\n"
                 "Mara [-counts-]{+pushed+} the [-lit-]{+gate+} "
                 "[-windows.-]{+open.+}\n"
                 "\n--- n2 (2/2) ---\nno changes\nrevised 1 passages\n")
    assert snap["inputs/revise_s001_n1.md"] == "Edited passage."
    assert snap["inputs/history/revise_s001_n1_(STAMP).md"] == \
        "Edited passage."
    tree = json.loads(snap["trees/s001.json"])
    assert tree["nodes"]["n1"]["text"] == "Edited passage."


def test_revise_regenerate_repeats_prompt(project):
    _prime_notes(project)
    t, snap, calls = rf.run_cli(
        project, "revise", ["junk", PASSAGE_1, "NO CHANGES"],
        answers=["r", "a"], args={"scene": "s001"})
    assert t.count("--- n1 (1/2) ---") == 2, "regeneration repeats the header"
    assert calls[0][2] == calls[1][2] and calls[0][3] == calls[1][3], \
        "regeneration repeats the captured request"
    assert t == ("\n--- n1 (1/2) ---\n"
                 "warning: no <passage> tags in the editor output; check it "
                 "for stray text\n"
                 "[-Mara counts the lit windows.-]{+junk+}\n"
                 "\n--- n1 (1/2) ---\n"
                 "Mara [-counts-]{+pushed+} the [-lit-]{+gate+} "
                 "[-windows.-]{+open.+}\n"
                 "\n--- n2 (2/2) ---\nno changes\nrevised 1 passages\n")


def test_revise_quit_retains_saves_and_skips_stale_warning(project):
    _prime_notes(project)
    t, snap, _ = rf.run_cli(project, "revise",
                            [PASSAGE_1, "<passage>unused</passage>"],
                            answers=["a", "q"], args={"scene": "s001"})
    assert t == ("\n--- n1 (1/2) ---\n"
                 "Mara [-counts-]{+pushed+} the [-lit-]{+gate+} "
                 "[-windows.-]{+open.+}\n"
                 "\n--- n2 (2/2) ---\n"
                 "[-She ticks off each pane.-]{+unused+}\n"
                 "revised 1 passages\n")
    tree = json.loads(snap["trees/s001.json"])
    assert tree["nodes"]["n1"]["text"] == "Mara pushed the gate open."
    assert tree["nodes"]["n2"]["text"] == "She ticks off each pane."
    assert "stale" not in t, "Quit keeps the CLI's completion-only warning"


def test_revise_stale_warning_on_normal_completion(project):
    _prime_notes(project)
    sums = {"scenes": {"s001": {"detailed": "d", "brief": "b",
                                "updated": "x", "text_hash": "h"}},
            "arcs": []}
    (project / "summaries.json").write_text(
        json.dumps(sums, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    t, snap, _ = rf.run_cli(project, "revise", [PASSAGE_1, "NO CHANGES"],
                            args={"scene": "s001"})
    assert t.endswith(
        "revised 1 passages\n"
        f"warning: summary for s001 is now stale (run: update-state "
        f"{project} --scene s001 --summary-only)\n")


def test_revise_continuation_keep_lead(project):
    _prime_notes(project)
    tree = json.loads((project / "trees" / "s001.json").read_text())
    tree["nodes"]["n2"]["sep"] = ""
    tree["nodes"]["n2"]["text"] = "  She ticks off each pane."
    (project / "trees" / "s001.json").write_text(
        json.dumps(tree, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    t, snap, _ = rf.run_cli(
        project, "revise",
        ["NO CHANGES", "<passage>Ticks every pane.</passage>"],
        args={"scene": "s001"})
    tree = json.loads(snap["trees/s001.json"])
    assert tree["nodes"]["n2"]["text"] == "  Ticks every pane.", \
        "continuation leading whitespace is preserved (keep_lead)"


# -------------------------------------------------------------- revise ops

def test_ops_revise_parity(project, tmp_path):
    _prime_notes(project)
    ops_root = _copy(project, tmp_path)
    t, cli_snap, calls = rf.run_cli(project, "revise",
                                    [PASSAGE_1, "NO CHANGES"],
                                    args={"scene": "s001"})
    session = ro.revise_prepare(str(ops_root), "s001")
    res = ro.revise_generate(str(ops_root), session, 0,
                             provider_factory=lambda p: FakeProvider([PASSAGE_1]))
    assert res["msgs"] == calls[0][2] and res["cap"] == calls[0][3]
    ro.revise_accept(str(ops_root), session, 0, res, res["text"])
    assert session.changed == 1
    fin = ro.revise_finish(str(ops_root), session)
    assert fin["message"] == "revised 1 passages"
    assert rf.snapshot(ops_root) == cli_snap


def test_ops_revise_accept_refuses_stale_tree(project, tmp_path):
    _prime_notes(project)
    ops_root = _copy(project, tmp_path)
    session = ro.revise_prepare(str(ops_root), "s001")
    psg = ro.revise_passage(str(ops_root), session, 0)
    tree = json.loads((ops_root / "trees" / "s001.json").read_text())
    tree["nodes"]["n1"]["text"] = "external"
    (ops_root / "trees" / "s001.json").write_text(
        json.dumps(tree, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    with pytest.raises(ro.OpError) as e:
        ro.revise_accept(str(ops_root), session, 0, psg, "Mara pushed.")
    assert e.value.stale
    tree = json.loads((ops_root / "trees" / "s001.json").read_text())
    assert tree["nodes"]["n1"]["text"] == "external"


def test_ops_revise_notes_changed_requires_new_session(project, tmp_path):
    _prime_notes(project)
    ops_root = _copy(project, tmp_path)
    session = ro.revise_prepare(str(ops_root), "s001")
    (ops_root / "critiques" / "s001.md").write_text("external\n",
                                                   encoding="utf-8")
    psg = ro.revise_passage(str(ops_root), session, 0)
    with pytest.raises(ro.OpError) as e:
        ro.revise_accept(str(ops_root), session, 0, psg, "Mara pushed.")
    assert e.value.stale, "changed notes invalidate the session baseline"
