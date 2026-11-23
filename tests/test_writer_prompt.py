"""Parity tests for build_writer_prompt against a stored fixed fixture.

tests/data/writer_prompt_fixture.json holds the prompt, samplers, and report for
scene start, continuation, and steer produced by the pre-extraction
implementation. The tests rebuild the same synthetic project offline and assert
byte-for-byte equality, so the load/compose split in longform.py cannot change
observable output. Regenerate the fixture only deliberately with
tests/data/gen_writer_fixture.py.
"""

import json
from pathlib import Path

import pytest

import longform

FIXTURE = Path(__file__).resolve().parent / "data" / "writer_prompt_fixture.json"

PRESET = {
    "preset": {},
    "instruct": {
        "macro": True,
        "input_sequence": "\n### Author:\n",
        "input_suffix": "\n",
        "output_sequence": "### Mara:\n",
    },
    "context": {
        "story_string": "{{#if system}}{{system}}\n\n{{/if}}{{description}}\n\n"
                        "{{#if scenario}}{{scenario}}\n\n{{/if}}---\n\n{{trim}}",
    },
    "sysprompt": {"content": "You narrate {{char}}. {{user}} steers the story."},
}

SCENES = [
    {"id": "s001", "chapter": 1, "title": "Arrival", "pov": "Mara",
     "setting": "the harbour", "characters": ["Mara", "Tomas"], "goal": "find the ledger",
     "conflict": "Tomas is watching", "target_words": 120},
    {"id": "s002", "chapter": 1, "title": "Ledger", "pov": "Mara",
     "characters": ["Mara"], "goal": "hide the ledger", "target_words": 100},
]


class FakeLore:
    def books(self):
        return []

    def entries(self, fname):
        raise AssertionError("no books expected")

    def char_name(self, fname, meta):
        return fname


def make_project(root):
    root.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(json.dumps(longform.DEFAULT_CONFIG))
    (root / "project.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    (root / "scenes.json").write_text(json.dumps(SCENES, indent=2) + "\n", encoding="utf-8")
    (root / "bible.md").write_text("# Story bible\n\nThe ledger hides the town's debts.\n", encoding="utf-8")
    (root / "state.md").write_text("Mara knows the ledger exists. Tomas suspects her.\n", encoding="utf-8")
    (root / "summaries.json").write_text(json.dumps(
        {"scenes": {"s001": {"detailed": "Mara searches the harbour office.",
                             "brief": "Mara searches."}},
         "arcs": []}, indent=2) + "\n", encoding="utf-8")
    (root / "trees").mkdir(exist_ok=True)
    tree = {
        "nodes": {
            "n1": {"id": "n1", "parent": None, "text": "The harbour smells of tar and rain.", "sep": "\n\n"},
            "n2": {"id": "n2", "parent": "n1", "text": "Mara kept to the shadows.", "sep": "\n\n"},
        },
        "head": "n2",
        "counter": 2,
    }
    (root / "trees" / "s001.json").write_text(json.dumps(tree, indent=2) + "\n", encoding="utf-8")
    empty = {"nodes": {}, "head": None, "counter": 0}
    (root / "trees" / "s002.json").write_text(json.dumps(empty, indent=2) + "\n", encoding="utf-8")
    return longform.Project(root)


@pytest.fixture(scope="module")
def expected():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture()
def project(tmp_path):
    return make_project(tmp_path / "proj")


def run_case(project, expected, case, scene_idx, steer, passage_words, tree_sid):
    tree = longform.Tree(project, tree_sid)
    prompt, params, extra, ignored, report = longform.build_writer_prompt(
        project, PRESET, FakeLore(), SCENES, scene_idx, tree, steer, passage_words)
    got = {"prompt": prompt, "params": params, "extra": extra,
           "ignored": ignored, "report": report}
    assert got == expected[case], (
        f"{case}: prompt mismatch\n"
        f"--- got ---\n{prompt[:2000]}\n"
        f"--- report diff ---\n{got['report']}\n!=\n{expected[case]['report']}"
    )


def test_scene_start_matches_fixture(project, expected):
    run_case(project, expected, "start", 0, "", 220, "s001")


def test_continuation_matches_fixture(project, expected):
    run_case(project, expected, "continue", 0, "", 220, "s001")


def test_steer_with_previous_scene_matches_fixture(project, expected):
    run_case(project, expected, "steer", 1, "Add rain.", 180, "s002")


# --------------------------------------------------------------------------- compose_writer_prompt


def test_compose_writer_prompt_is_pure_and_deterministic(tmp_path):
    est = lambda model, text: len(text or "") // 10 + 1  # noqa: E731
    ratio = lambda model: 3.5  # noqa: E731
    scenes = [{"id": "s1", "chapter": 1, "title": "One", "characters": ["Mara"], "target_words": 50}]
    ins = {"input_sequence": "\n### Author:\n", "input_suffix": "\n", "output_sequence": "### Mara:\n"}
    story_string = "{{description}}\n\n{{scenario}}\n\n---"
    mac = lambda s, name=None: (s or "").replace("{{char}}", "Mara")  # noqa: E731
    lfields = {"wiBefore": "", "description": "a thief", "wiAfter": ""}
    card = "Scene s1 (Chapter 1): One"
    sums = {"scenes": {"s1": {"detailed": "D", "brief": "B"}}, "arcs": []}
    common = dict(
        scenes=scenes, idx=0, ins=ins, story_string=story_string, mac=mac, char="Mara", user="Author",
        bible="The bible.", state="State.", card=card, scene_text="", continuing=False, prev_src="",
        steer="", passage_words=100, lfields=lfields, cast="Cast.", progress="Progress.",
        system="Sys.", out_seq="### Mara:\n", sums=sums, summary_cfg={"detailed_recent_scenes": 1},
        est=est, ratio=ratio, model="m", root="/proj",
    )
    first = longform.compose_writer_prompt(3000, 5000, **common)
    second = longform.compose_writer_prompt(3000, 5000, **common)
    assert first == second
    prompt, parts, snotes = first
    assert parts["bible"] == est("m", "The bible.")
    assert "The bible." in prompt and "Continuity state:\nState." in prompt
    assert snotes == []
    # a missing summary surfaces the deterministic note through the composition
    two = [{"id": "s1", "chapter": 1, "title": "One", "characters": ["Mara"], "target_words": 50},
           {"id": "s2", "chapter": 1, "title": "Two", "characters": ["Mara"], "target_words": 50}]
    _, _, snotes = longform.compose_writer_prompt(
        3000, 5000, **{**common, "scenes": two, "idx": 1,
                       "sums": {"scenes": {}, "arcs": []}})
    assert snotes == ["s1 has no summary (run: update-state /proj --scene s1)"]
