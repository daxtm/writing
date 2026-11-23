"""Resume visibility in the interactive draft loop.

The draft prompt is interactive and offline at startup; these tests drive it
through stdin and assert what a returning author can see without generating.
"""

import json
import subprocess
import sys
from pathlib import Path

import longform

REPO = Path(longform.__file__).resolve().parent

PRESET = {
    "preset": {"temp": 1.0, "genamt": 50},
    "instruct": {
        "macro": True,
        "input_sequence": "\n",
        "input_suffix": "\n",
        "output_sequence": "\n",
        "stop_sequence": "",
    },
    "context": {"story_string": "{{description}}"},
    "sysprompt": {"content": "You narrate {{char}}."},
}

OPENING = "OPENING THAT SHOULD NOT APPEAR IN THE RESUME TAIL."
ENDING = "THE LAST SEGMENT ENDS HERE."
LONG_TEXT = OPENING + "\n\n" + ("Mara crosses the yard and counts the lit windows. " * 30) + "\n\n" + ENDING


def make_project(root):
    root.mkdir(parents=True)
    (root / "project.json").write_text(json.dumps({"title": "Resume test"}) + "\n", encoding="utf-8")
    (root / "writer_preset.json").write_text(json.dumps(PRESET) + "\n", encoding="utf-8")
    (root / "bible.md").write_text("# Story bible\n\nA quiet town.\n", encoding="utf-8")
    (root / "state.md").write_text("Mara is at the yard.\n", encoding="utf-8")
    (root / "scenes.json").write_text(json.dumps([{
        "id": "s001", "chapter": 1, "title": "Yard", "pov": "Mara",
        "characters": ["Mara"], "goal": "count the windows", "target_words": 100,
        "status": "drafting",
    }]) + "\n", encoding="utf-8")
    (root / "summaries.json").write_text(json.dumps({"scenes": {}, "arcs": []}) + "\n", encoding="utf-8")
    (root / "trees").mkdir()
    (root / "trees" / "s001.json").write_text(json.dumps({
        "nodes": {
            "n1": {
                "id": "n1", "parent": None, "text": LONG_TEXT, "sep": "\n\n",
                "source": "model", "created": "2026-11-23 10:00", "model": "test-model",
                "steer": "keep it quiet",
            },
            "n2": {
                "id": "n2", "parent": None, "text": "An alternate take kept as a branch.",
                "sep": "\n\n", "source": "model", "created": "2026-11-23 10:01", "model": "test-model",
            },
        },
        "head": "n1", "counter": 2,
    }) + "\n", encoding="utf-8")
    return root


def draft(root, stdin, env):
    return subprocess.run(
        [sys.executable, str(REPO / "longform.py"), "draft", str(root), "--scene", "s001"],
        input=stdin, text=True, capture_output=True, timeout=30, env=env,
    )


def test_resume_shows_head_ending_and_sibling_branches(tmp_path, net_guard_env):
    root = make_project(tmp_path / "proj")
    r = draft(root, "q\n", net_guard_env)
    assert r.returncode == 0, r.stderr
    assert "resume n1" in r.stdout
    assert "ends:" in r.stdout
    assert ENDING in r.stdout
    assert "steer used: keep it quiet" in r.stdout
    assert "1 other branch(es): n2" in r.stdout
    # the resume tail must not dump the whole passage
    assert OPENING not in r.stdout


def test_v_by_id_and_tail_command(tmp_path, net_guard_env):
    root = make_project(tmp_path / "proj")
    r = draft(root, "v n2\ntail 25\nq\n", net_guard_env)
    assert r.returncode == 0, r.stderr
    assert "===== n2" in r.stdout
    assert "An alternate take kept as a branch." in r.stdout
    assert "no such node" not in r.stdout
    assert "last 25 chars (head n1):" in r.stdout
    assert "ENDS HERE." in r.stdout
    # v n2 shows only that node, not the active n1 passage
    assert OPENING not in r.stdout
