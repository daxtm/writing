"""CLI/operation parity for the shared draft loop (task 1.2).

Baselines were captured from the pre-extraction `cmd_draft` (fake provider,
scripted terminal choices): prompt/request bytes, saved tree/scenes and the
fixed stdout transcript below are frozen and must stay identical now that the
CLI is an adapter over draft_operations. All offline: fake provider, temp
projects, no network.
"""

import json
import types
from pathlib import Path

import pytest

import longform_core.commands as commands
from longform_core import draft_operations as dop
from longform_core.api import HttpErr
from longform_core.project import Project

PRESET = {
    "preset": {"temp": 1.0, "genamt": 50},
    "instruct": {"macro": True, "input_sequence": "\n", "input_suffix": "\n",
                 "output_sequence": "\n", "stop_sequence": ""},
    "context": {"story_string": "{{description}}"},
    "sysprompt": {"content": "You narrate {{char}}."},
}

STREAMED = "CHUNK ONE of the yard scene."
BATCH_A = "BATCH A text."
BATCH_B = "BATCH B text."
REBUT = "REBUTTAL text."


def build(root, **extra):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    cfg = {"title": "T", "api_key": "sk-test"}
    cfg.update(extra)
    (root / "project.json").write_text(json.dumps(cfg) + "\n", encoding="utf-8")
    (root / "writer_preset.json").write_text(json.dumps(PRESET) + "\n", encoding="utf-8")
    (root / "bible.md").write_text("# Story bible\n\nQuiet town.\n", encoding="utf-8")
    (root / "state.md").write_text("Mara is at the yard.\n", encoding="utf-8")
    (root / "scenes.json").write_text(json.dumps([{
        "id": "s001", "chapter": 1, "title": "Yard", "pov": "Mara",
        "characters": ["Mara"], "goal": "count windows", "target_words": 100,
        "status": "planned"}]) + "\n", encoding="utf-8")
    (root / "summaries.json").write_text(json.dumps({"scenes": {}, "arcs": []}) + "\n", encoding="utf-8")
    (root / "trees").mkdir(exist_ok=True)
    (root / "trees" / "s001.json").write_text(json.dumps({
        "nodes": {"n1": {"id": "n1", "parent": None,
                         "text": "Mara counts the lit windows.", "sep": "",
                         "created": "2026-11-23 10:00", "history": [],
                         "source": "model", "model": "m1", "steer": "keep it quiet"}},
        "head": "n1", "counter": 1}) + "\n", encoding="utf-8")
    return root


class FakeProvider:
    """Same surface as Api; script is a list of texts or exceptions."""

    script = []
    instances = []

    def __init__(self, p):
        self.p = p
        self.calls = []
        FakeProvider.instances.append(self)

    def complete(self, role, prompt, params, extra=None, stream_cb=None, meta=None,
                 token=None, **kw):
        i = len(self.calls)
        self.calls.append({"prompt": prompt, "params": dict(params),
                           "extra": dict(extra or {}), "meta": dict(meta or {})})
        item = FakeProvider.script[i] if i < len(FakeProvider.script) else "FALLBACK TEXT."
        if isinstance(item, Exception):
            raise item
        if stream_cb:
            stream_cb(item)
        self.p.record_calib("meta-llama/Llama-3.3-70B-Instruct", len(prompt), 40)
        return item, "stop", {"prompt_tokens": 40, "completion_tokens": 12}

    def many(self, fn, n, token=None, on_event=None):
        out = []
        for k in range(1, n + 1):
            try:
                out.append(fn())
                if on_event:
                    on_event({"type": "candidate_done", "k": k, "n": n, "msg": f"  candidate {k}/{n} done"})
                else:
                    print(f"  candidate {k}/{n} done", flush=True)
            except Exception as e:  # noqa: BLE001 (mirrors Api.many)
                if on_event:
                    on_event({"type": "candidate_failed", "k": k, "n": n,
                              "msg": f"  candidate {k}/{n} failed: {type(e).__name__}: {e}"})
                else:
                    print(f"  candidate {k}/{n} failed: {type(e).__name__}: {e}", flush=True)
        return out


def run_cli(root, script, monkeypatch, capsys, scene=None, responses=None):
    """Drive cmd_draft in-process with scripted answers and a fake provider."""
    answers = iter(script)
    monkeypatch.setattr(commands, "ask", lambda *a, **k: next(answers))
    FakeProvider.instances = []
    FakeProvider.script = list(responses or [])
    monkeypatch.setattr(commands, "Api", FakeProvider)
    p = Project(root)
    commands.cmd_draft(p, types.SimpleNamespace(scene=scene))
    return capsys.readouterr().out


def run_ops(root, responses, count=1, events=None, parent=None):
    FakeProvider.instances = []
    FakeProvider.script = list(responses or [])
    return dop.generate_candidates(root, "s001", count=count, steer="", parent=parent,
                                   provider_factory=lambda p: FakeProvider(p),
                                   events=events)


def _norm_tree(root):
    t = json.loads((Path(root) / "trees" / "s001.json").read_text(encoding="utf-8"))
    for n in t["nodes"].values():
        n.pop("created", None)
    return t


# The CLI stdout transcript with fake answers "g1, accept 1, quit", captured
# byte-for-byte from the pre-extraction interactive loop.
FROZEN_TRANSCRIPT = """writer preset: writer_preset.json  temp 1.06
Scene s001 (Chapter 1): Yard
POV: Mara
Characters present: Mara
Goal: count windows
Target length: ~100 words
no lorebooks in {root}/lorebooks
resume n1  5 words  model  m1
  ends: Mara counts the lit windows.
  steer used: keep it quiet
type ? for commands
--- streaming ---
CHUNK ONE of the yard scene.

===== [1] n2  6 words
accepted n2
"""


def test_cli_routes_generate_through_shared_operation(tmp_path, monkeypatch, capsys):
    """The CLI is an adapter: generation must run through draft_operations."""
    root = build(tmp_path / "p")
    calls = []
    real = dop.generate_candidates

    def spy(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(dop, "generate_candidates", spy)
    out = run_cli(root, ["g1\n", "1\n", "q\n"], monkeypatch, capsys, responses=[STREAMED])
    assert calls, "cmd_draft must run generation through draft_operations.generate_candidates"
    assert "CHUNK ONE" in out


def test_cli_and_operations_match_on_streamed_generation(tmp_path, monkeypatch, capsys):
    """Same prompt/request bytes, metadata and saved tree for CLI and ops."""
    root = build(tmp_path / "p")
    out = run_cli(root, ["g1\n", "1\n", "q\n"], monkeypatch, capsys, responses=[STREAMED])
    cli_calls = FakeProvider.instances[0].calls
    cli_tree = _norm_tree(root)
    cli_scenes = json.loads((root / "scenes.json").read_text(encoding="utf-8"))
    cli_calib = (root / "calib.json").read_text(encoding="utf-8")

    root2 = build(tmp_path / "p2")
    res = run_ops(root2, [STREAMED])
    dop.accept_candidate(root2, "s001", res.saved[0])
    ops_calls = FakeProvider.instances[0].calls
    assert cli_calls == ops_calls, "prompt bytes, params, extra and meta must match"
    assert cli_tree == _norm_tree(root2), "saved nodes match (created normalized)"
    assert cli_scenes == json.loads((root2 / "scenes.json").read_text(encoding="utf-8"))
    assert cli_calib == (root2 / "calib.json").read_text(encoding="utf-8"), \
        "guarded calibration side effects match"
    # transcript frozen: the CLI prints exactly the pre-extraction bytes
    assert out == FROZEN_TRANSCRIPT.format(root=root)


def test_cli_and_operations_match_on_batch(tmp_path, monkeypatch, capsys):
    """Default swipes=2 batch: same ordering, saved ids and head behavior."""
    root = build(tmp_path / "p")
    run_cli(root, ["g\n", "\n", "q\n"], monkeypatch, capsys,
            responses=[BATCH_A, BATCH_B])
    cli_calls = FakeProvider.instances[0].calls
    cli_tree = _norm_tree(root)
    head = cli_tree["head"]
    assert head == "n1", "no implicit acceptance in a batch"
    assert "BATCH A text." in cli_tree["nodes"]["n2"]["text"]
    assert "BATCH B text." in cli_tree["nodes"]["n3"]["text"]

    root2 = build(tmp_path / "p2")
    run_ops(root2, [BATCH_A, BATCH_B], count=2)
    assert cli_calls == FakeProvider.instances[0].calls
    assert cli_tree == _norm_tree(root2)


def test_budget_refusal_calls_nothing(tmp_path, monkeypatch, capsys):
    """Over the context ceiling: the report is printed and no call is made."""
    root = build(tmp_path / "p", max_context_fallback=200)
    out = run_cli(root, ["g\n", "q\n"], monkeypatch, capsys)
    assert FakeProvider.instances == [] or all(not i.calls for i in FakeProvider.instances), \
        "over budget must not call"
    assert "OVER the context ceiling" in out
    tree = _norm_tree(root)
    assert set(tree["nodes"]) == {"n1"} and tree["head"] == "n1"

    res = run_ops(root, [], count=2)
    assert all(not i.calls for i in FakeProvider.instances)
    assert res.over and res.saved == []
    assert _norm_tree(root) == tree


def test_partial_batch_failure_keeps_completed_candidates(tmp_path, monkeypatch, capsys):
    """One good, one failed: the completed candidate is saved, head unchanged."""
    root = build(tmp_path / "p")
    out = run_cli(root, ["g\n", "\n", "q\n"], monkeypatch, capsys,
                  responses=[BATCH_A, HttpErr(500, "boom")])
    assert "candidate 2/2 failed" in out
    assert "generation failed" not in out  # a batch member failing is not fatal
    tree = _norm_tree(root)
    assert tree["head"] == "n1"
    assert tree["nodes"]["n2"]["text"] == BATCH_A

    events = []
    root2 = build(tmp_path / "p2")
    res = run_ops(root2, [BATCH_A, HttpErr(500, "boom")], count=2, events=events.append)
    assert res.saved == ["n2"] and res.shortfall == 1
    assert {"type": "candidate_failed", "k": 2, "n": 2,
            "msg": "  candidate 2/2 failed: HttpErr: HTTP 500: boom"} in events
    assert _norm_tree(root2) == tree


def test_generation_failure_is_soft(tmp_path, monkeypatch, capsys):
    """A failed single stream reports and keeps head/branches; no node."""
    root = build(tmp_path / "p")
    out = run_cli(root, ["g1\n", "q\n"], monkeypatch, capsys,
                  responses=[HttpErr(500, "boom")])
    assert "generation failed: HTTP 500: boom" in out
    tree = _norm_tree(root)
    assert set(tree["nodes"]) == {"n1"} and tree["head"] == "n1"

    with pytest.raises(dop.OpError) as e:
        run_ops(root, [HttpErr(500, "boom")])
    assert e.value.soft and not e.value.stale
    assert _norm_tree(root) == tree


def test_reroll_keeps_originals_and_matches_shared_operation(tmp_path, monkeypatch, capsys):
    """`r 1` replaces the slot, keeps the original as a branch and matches ops."""
    root = build(tmp_path / "p")
    out = run_cli(root, ["g\n", "r 1\n", "\n", "q\n"], monkeypatch, capsys,
                  responses=[BATCH_A, BATCH_B, REBUT])
    tree = _norm_tree(root)
    assert tree["head"] == "n1", "reroll never moves the head"
    assert "BATCH A text." in tree["nodes"]["n2"]["text"], "original kept as branch"
    assert tree["nodes"]["n4"]["text"] == REBUT, "new sibling of the batch parent"
    assert "[1] n2 rerolled -> n4 (old text kept as a branch)" in out
    # all candidates (old and new) share the batch's captured parent
    assert tree["nodes"]["n4"]["parent"] == "n1" == tree["nodes"]["n2"]["parent"]

    root2 = build(tmp_path / "p2")
    res = run_ops(root2, [BATCH_A, BATCH_B], count=2)
    first = [dict(c) for c in FakeProvider.instances[0].calls]
    run_ops(root2, [REBUT], count=1, parent=res.parent)
    ops_calls = first + [dict(c) for c in FakeProvider.instances[0].calls]

    root3 = build(tmp_path / "p3")
    run_cli(root3, ["g\n", "r 1\n", "\n", "q\n"], monkeypatch, capsys,
            responses=[BATCH_A, BATCH_B, REBUT])
    assert FakeProvider.instances[0].calls == ops_calls, \
        "reroll prompt/meta matches the batch parent capture"
    assert _norm_tree(root2) == _norm_tree(root3) == tree


def test_delete_leaf_rules(tmp_path, monkeypatch, capsys):
    """Leaf deletion works (a head leaf moves head to parent); nonleaf refused."""
    root2 = build(tmp_path / "p2")
    run_cli(root2, ["g\n", "d 2\n", "\n", "q\n"], monkeypatch, capsys,
            responses=[BATCH_A, BATCH_B])
    tree = _norm_tree(root2)
    assert "n3" not in tree["nodes"], "deleted leaf removed"
    assert "n2" in tree["nodes"], "kept candidate untouched"
    assert tree["head"] == "n1"

    # op parity: same deletion on a fresh project
    root3 = build(tmp_path / "p3")
    res = run_ops(root3, [BATCH_A, BATCH_B], count=2)
    dop.delete_leaf(root3, "s001", res.saved[1])
    assert _norm_tree(root3) == tree

    # nonleaf refusal: delete a node with children
    root4 = build(tmp_path / "p4")
    t = json.loads((root4 / "trees" / "s001.json").read_text(encoding="utf-8"))
    t["nodes"]["n2"] = {"id": "n2", "parent": "n1", "text": "parent passage",
                        "created": "x", "history": [], "sep": "\n\n"}
    t["nodes"]["n3"] = {"id": "n3", "parent": "n2", "text": "child",
                        "created": "x", "history": [], "sep": "\n\n"}
    t["head"] = "n3"
    t["counter"] = 3
    (root4 / "trees" / "s001.json").write_text(json.dumps(t), encoding="utf-8")
    with pytest.raises(dop.OpError) as e:
        dop.delete_leaf(root4, "s001", "n2")
    assert "has children" in str(e.value)
    after = json.loads((root4 / "trees" / "s001.json").read_text(encoding="utf-8"))
    assert set(after["nodes"]) == {"n1", "n2", "n3"}

    # a deleted head leaf moves the head to its parent
    dop.delete_leaf(root4, "s001", "n3")
    after = json.loads((root4 / "trees" / "s001.json").read_text(encoding="utf-8"))
    assert after["head"] == "n2"


def test_scene_controls_parity(tmp_path, monkeypatch, capsys):
    """who/pov/d CLI semantics match the shared operations; prompts match."""
    root = build(tmp_path / "p")
    out = run_cli(root, ["who Mara, Tom\n", "pov Mara\n", "d\n"],
                  monkeypatch, capsys)
    assert "present: Mara, Tom" in out
    assert "pov: Mara" in out
    assert "scene s001 done. next step: update-state" in out
    scenes = json.loads((root / "scenes.json").read_text(encoding="utf-8"))
    assert scenes[0]["characters"] == ["Mara", "Tom"]
    assert scenes[0]["pov"] == "Mara"
    assert scenes[0]["status"] == "done"
    cli_prompt = dop.prepare_report(root, "s001")["prompt"]

    root2 = build(tmp_path / "p2")
    dop.set_cast(root2, "s001", ["Mara", "Tom"])
    dop.set_pov(root2, "s001", "Mara")
    dop.mark_done(root2, "s001")
    assert json.loads((root2 / "scenes.json").read_text(encoding="utf-8")) == scenes
    assert dop.prepare_report(root2, "s001")["prompt"] == cli_prompt, \
        "next prompts are byte-identical after POV/cast changes"


def test_prompt_dump_parity(tmp_path, monkeypatch, capsys):
    """CLI cp and the operation write the same exact bytes; no call."""
    root = build(tmp_path / "p")
    out = run_cli(root, ["cp\n", "q\n"], monkeypatch, capsys)
    assert "wrote" in out and "last_prompt.txt" in out
    dumped = (root / "last_prompt.txt").read_bytes()

    root2 = build(tmp_path / "p2")
    res = dop.dump_prompt(root2, "s001")
    assert (root2 / "last_prompt.txt").read_bytes() == dumped
    assert res["path"].endswith("last_prompt.txt")


def test_accept_matches_shared_operation(tmp_path, monkeypatch, capsys):
    """Accept moves head, planned->drafting; other candidates stay branches."""
    root = build(tmp_path / "p")
    out = run_cli(root, ["g\n", "2\n", "q\n"], monkeypatch, capsys,
                  responses=[BATCH_A, BATCH_B])
    tree = _norm_tree(root)
    assert tree["head"] == "n3", "accepting candidate 2"
    assert "accepted n3" in out
    scenes = json.loads((root / "scenes.json").read_text(encoding="utf-8"))
    assert scenes[0]["status"] == "drafting"
    assert "BATCH A text." in tree["nodes"]["n2"]["text"], "reroll target kept"

    root2 = build(tmp_path / "p2")
    res = run_ops(root2, [BATCH_A, BATCH_B], count=2)
    dop.accept_candidate(root2, "s001", res.saved[1])
    assert _norm_tree(root2) == _norm_tree(root)
    scenes2 = json.loads((root2 / "scenes.json").read_text(encoding="utf-8"))
    assert scenes2 == scenes
