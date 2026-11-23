"""Lore registry/prompt parity and import rules for shared operations (1.7).

Headless: CLI `lb` adapters vs draft_operations on identical synthetic
projects, plus import validation/collision/stale rules through the existing
parser/discovery. Offline fixtures only.
"""

import base64
import json
import struct
import zlib
from pathlib import Path

import pytest

from longform_core import draft_operations as dop

from tests.test_draft_parity import build

WORLD = {"entries": {"0": {"comment": "tower", "key": ["tower"],
                           "content": "The tower overlooks the harbour.",
                           "enabled": True, "constant": False}}}
V1 = {"name": "Mara", "description": "a harbour thief", "personality": "wry"}
V2 = {"spec": "chara_card_v2", "data": {"name": "Ivo", "description": "a smith",
                                        "character_book": {"entries": [
                                            {"comment": "forge", "key": ["forge"],
                                             "content": "The forge never cools."}]}}}
V3 = {"spec": "chara_card_v3", "data": {"name": "Sela", "description": "a pilot"}}
EMPTY = {"entries": {}}


def chunk(ctype, body):
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", zlib.crc32(ctype + body))


def card_png(card):
    payload = base64.b64encode(json.dumps(card).encode("utf-8"))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"tEXt", b"chara\x00" + payload)
            + chunk(b"IEND", b""))


def make_project(root, books=()):
    root = build(root, scenes=[{"id": "s001", "chapter": 1, "title": "Yard",
                                "pov": "Mara", "characters": ["Mara"],
                                "goal": "count windows", "target_words": 100,
                                "status": "planned"}])
    lb = root / "lorebooks"
    lb.mkdir(exist_ok=True)
    for name, data in books:
        (lb / name).write_bytes(data)
    return root


def reg(root):
    return json.loads((Path(root) / "lorebooks.json").read_text(encoding="utf-8"))


def test_lore_control_parity(tmp_path, monkeypatch, capsys):
    """CLI lb toggles/classification match the shared operations, and the next
    prompt (matching/injected lore) is byte-identical."""
    import tests.test_draft_parity as tp

    def books(path):
        p = make_project(path, [("wi.json", json.dumps(WORLD).encode()),
                                ("mara.json", json.dumps(V1).encode())])
        return p

    root = books(tmp_path / "p")
    out = run = tp.run_cli(root, ["lb\n", "lb 1\n", "lb all on\n",
                                  "lb 2 alias M, R\n", "lb 1 world\n", "q\n"],
                           monkeypatch, capsys)
    assert "lorebooks (" in out
    cli_reg = reg(root)
    cli_prompt = dop.prepare_report(root, "s001")["prompt"]

    root2 = books(tmp_path / "p2")
    dop.lore_toggle(root2, "s001", [1])
    dop.lore_set_all(root2, "s001", True)
    dop.lore_set_aliases(root2, "s001", 2, ["M", "R"])
    dop.lore_set_world(root2, "s001", 1)
    assert reg(root2) == cli_reg, "registry matches equivalent lb actions"
    assert dop.prepare_report(root2, "s001")["prompt"] == cli_prompt, \
        "matching/injected lore reaches the prompt identically"
    rows = dop.lore_rows(root2, "s001")
    assert [r["file"] for r in rows] == ["mara.json", "wi.json"]
    assert all(r["on"] for r in rows)
    assert rows[0]["kind"] == "world", "lb 1 world applied to book 1"
    assert all(r["entries"] >= 1 for r in rows), "every book stays listed"


def test_lore_set_char_requires_name(tmp_path):
    root = make_project(tmp_path / "p", [("wi.json", json.dumps(WORLD).encode())])
    with pytest.raises(dop.OpError) as e:
        dop.lore_set_char(root, "s001", 1, "")
    assert "usage" in str(e.value)
    with pytest.raises(dop.OpError) as e:
        dop.lore_toggle(root, "s001", [9])
    assert "no such lorebook number" in str(e.value)
    assert reg(root)["books"]["wi.json"] == \
        {"on": False, "kind": "world", "character": "", "aliases": []}, \
        "refusals change no classification"


def test_lore_import_rules(tmp_path):
    root = make_project(tmp_path / "p")
    src = tmp_path / "imports"
    src.mkdir()
    fixtures = {
        "world.json": WORLD,
        "v1.json": V1, "v2.json": V2, "v3.json": V3, "empty.json": EMPTY,
    }
    for name, d in fixtures.items():
        (src / name).write_text(json.dumps(d), encoding="utf-8")
    (src / "card.png").write_bytes(card_png({"name": "Png Chara",
                                             "description": "from a png"}))
    (src / "broken.json").write_text("{nope", encoding="utf-8")
    (src / "notpng.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    res = dop.lore_import(root, src / "world.json", "s001")
    assert res["imported"] == "world.json" and res["card_name"] is None
    assert (root / "lorebooks" / "world.json").read_bytes() == \
        (src / "world.json").read_bytes(), "unchanged bytes are copied"
    assert reg(root)["books"]["world.json"]["kind"] == "world"

    for name, expected_char in (("v1.json", "Mara"), ("v2.json", "Ivo"),
                                ("v3.json", "Sela"), ("card.png", "Png Chara")):
        res = dop.lore_import(root, src / name, "s001")
        assert reg(root)["books"][name]["kind"] == "character"
        assert reg(root)["books"][name]["character"] == expected_char

    res = dop.lore_import(root, src / "empty.json", "s001")
    assert res["entries"] == 0, "valid empty books remain empty"
    rows = dop.lore_rows(root, "s001")
    assert {r["file"] for r in rows} >= set(fixtures) | {"card.png"}
    assert any(r["role"] == "POV" and r["who"].startswith("Mara")
               for r in rows), "character role is classified against the scene"

    before_reg = reg(root)
    before_files = sorted(x.name for x in (root / "lorebooks").iterdir())
    with pytest.raises(dop.OpError) as e:
        dop.lore_import(root, src / "broken.json", "s001")
    assert "not valid JSON" in str(e.value)
    with pytest.raises(dop.OpError) as e:
        dop.lore_import(root, src / "notpng.png", "s001")
    assert "no character card data" in str(e.value)
    assert reg(root) == before_reg and \
        sorted(x.name for x in (root / "lorebooks").iterdir()) == before_files, \
        "invalid/unreadable inputs write nothing"


def test_lore_import_collision_and_replace(tmp_path):
    root = make_project(tmp_path / "p")
    src = tmp_path / "imports"
    src.mkdir()
    (src / "book.json").write_text(json.dumps(WORLD), encoding="utf-8")
    dop.lore_import(root, src / "book.json", "s001")
    dop.lore_set_char(root, "s001", 1, "Renamed")

    with pytest.raises(dop.OpError) as e:
        dop.lore_import(root, src / "book.json", "s001")
    assert e.value.collision and "destination exists" in str(e.value)
    dest = (root / "lorebooks" / "book.json").read_bytes()
    assert reg(root)["books"]["book.json"]["character"] == "Renamed"

    # Replace: destination bytes replaced, registry metadata preserved
    (src / "book.json").write_text(json.dumps(V2), encoding="utf-8")
    res = dop.lore_import(root, src / "book.json", "s001", replace=True)
    assert res["replaced"] is True
    assert (root / "lorebooks" / "book.json").read_bytes() != dest
    assert reg(root)["books"]["book.json"]["character"] == "Renamed", \
        "existing registry metadata for the name is preserved"
