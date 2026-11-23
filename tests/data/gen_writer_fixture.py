"""One-shot generator for tests/data/writer_prompt_fixture.json.

Run with: uv run --with httpx tests/data/gen_writer_fixture.py
Captures build_writer_prompt output (prompt + report) for scene start,
continuation, and steer from the current implementation. Re-run only to
re-baseline deliberately; the parity test compares against the stored file.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import longform  # noqa: E402

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


def main():
    p = make_project(Path("/tmp/opencode/wfix"))
    cases = {}
    tree = longform.Tree(p, "s001")
    prompt, params, extra, ignored, report = longform.build_writer_prompt(
        p, PRESET, FakeLore(), SCENES, 0, tree, "", 220)
    cases["start"] = {"prompt": prompt, "params": params, "extra": extra,
                      "ignored": ignored, "report": report}
    prompt, params, extra, ignored, report = longform.build_writer_prompt(
        p, PRESET, FakeLore(), SCENES, 0, tree, "", 220)
    cases["continue"] = {"prompt": prompt, "params": params, "extra": extra,
                         "ignored": ignored, "report": report}
    prompt, params, extra, ignored, report = longform.build_writer_prompt(
        p, PRESET, FakeLore(), SCENES, 1, longform.Tree(p, "s002"), "Add rain.", 180)
    cases["steer"] = {"prompt": prompt, "params": params, "extra": extra,
                      "ignored": ignored, "report": report}
    out = Path(__file__).resolve().parent / "writer_prompt_fixture.json"
    out.write_text(json.dumps(cases, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
