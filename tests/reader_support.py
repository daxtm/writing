"""Shared synthetic project builders for desktop-reader tests (offline, temp dirs)."""
import json
from pathlib import Path

NOW = "2026-01-01T00:00:00+00:00"


def node(nid, parent, text, sep="\n\n", created=NOW, history=None, **meta):
    d = {"id": nid, "parent": parent, "text": text, "created": created,
         "history": history or []}
    if sep is not None:
        d["sep"] = sep
    d.update(meta)
    return d


def tree(nodes, head=None):
    counter = max([int(n["id"][1:]) for n in nodes.values()
                   if n["id"][1:].isdigit()] or [0])
    return {"nodes": nodes, "head": head, "counter": counter}


def scene(sid, chapter=1, title="", status="planned", target=1000, **extra):
    d = {"id": sid, "chapter": chapter, "title": title, "target_words": target,
         "status": status}
    d.update(extra)
    return d


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")


def write_text(path, text):
    Path(path).write_text(text, encoding="utf-8")


def build_project(root, *, title="Test Title", target=17000, scenes=None,
                  trees=None, project_extra=None, bible=None, state=None,
                  summaries=None, checks=None, critiques=None):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "trees").mkdir(exist_ok=True)
    cfg = {"title": title, "target_words": target}
    if project_extra:
        cfg.update(project_extra)
    write_json(root / "project.json", cfg)
    write_json(root / "scenes.json", scenes if scenes is not None else [])
    write_json(root / "summaries.json",
               summaries if summaries is not None else {"scenes": {}, "arcs": []})
    for sid, t in (trees or {}).items():
        write_json(root / "trees" / f"{sid}.json", t)
    if bible is not None:
        write_text(root / "bible.md", bible)
    if state is not None:
        write_text(root / "state.md", state)
    for sub, files in (("checks", checks or {}), ("critiques", critiques or {})):
        (root / sub).mkdir(exist_ok=True)
        for name, text in files.items():
            write_text(root / sub / name, text)
    return root
