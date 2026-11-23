"""Display-independent, data-only snapshots of a writing project for the reader.

No Tk, no CLI `Project`, no provider access, no credentials, no `die()`.
Filesystem access is confined to this module's small read boundary below the
one canonical project root. All diagnostics are sanitized: relative source
names only, never raw file contents, exceptions, absolute paths, or
configuration values.
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .tree import Tree
from .utils import words

# Scene IDs / tree stems: ASCII letters, digits, underscore, hyphen only.
_ID_RE = re.compile(r"[A-Za-z0-9_-]+\Z")

DEFAULT_TITLE = "Untitled"
DEFAULT_TARGET = 17000


@dataclass
class ProjectInfo:
    """Only public project identity; never other configuration fields."""

    title: str = DEFAULT_TITLE
    target_words: int = DEFAULT_TARGET


@dataclass
class NodeInfo:
    id: str
    parent: str | None
    children: list[str] = field(default_factory=list)
    text: str = ""
    word_count: int = 0
    source: str | None = None
    model: str | None = None
    created: str | None = None
    steer: str | None = None
    ended: bool | None = None
    trimmed: bool | None = None
    history: list[dict] = field(default_factory=list)  # {time, by, text}
    sep: str = "\n\n"
    link_ok: bool = True
    on_active_path: bool = False


@dataclass
class TreeView:
    id: str
    nodes: dict[str, NodeInfo] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)  # persisted insertion order
    head: str | None = None
    active_text: str | None = None  # None means unavailable (broken links)
    active_words: int | None = None
    active_ids: list[str] | None = None
    broken: bool = False  # file unreadable / not valid JSON / invalid shape
    warnings: list[str] = field(default_factory=list)


@dataclass
class SceneRow:
    id: str
    tree_id: str
    chapter: str
    title: str
    status: str
    target_words: int
    group: str


@dataclass
class NoteFile:
    name: str
    text: str


@dataclass
class SummaryEntry:
    scene_id: str
    detailed: str | None
    brief: str | None
    updated: str | None


@dataclass
class ArcEntry:
    from_id: str
    to_id: str
    text: str
    updated: str | None


@dataclass
class SummariesView:
    scenes: dict[str, SummaryEntry] = field(default_factory=dict)
    arcs: list[ArcEntry] = field(default_factory=list)


@dataclass
class NotesView:
    bible: str | None = None      # None = missing or unreadable source
    state: str | None = None
    summaries: SummariesView | None = None
    checks: list[NoteFile] = field(default_factory=list)
    critiques: list[NoteFile] = field(default_factory=list)


@dataclass
class Snapshot:
    project: ProjectInfo
    scenes: list[SceneRow]
    trees: dict[str, TreeView]
    notes: NotesView
    actual_words: int
    words_complete: bool
    warnings: list[str] = field(default_factory=list)


@dataclass
class LoadResult:
    snapshot: Snapshot | None  # None only for invalid required configuration
    warnings: list[str]


@dataclass
class FileMeta:
    mtime_ns: int
    size: int
    st_ino: int
    st_dev: int


@dataclass
class CacheEntry:
    meta: FileMeta
    raw: object  # parsed JSON or decoded text, reused without a fresh read


@dataclass
class SourceCache:
    """Optional caching inputs, separate from displayed data.

    Tracks which relative sources were freshly read so tests (and the UI) can
    prove unchanged automatic refreshes do not reread disk.
    """

    entries: dict[str, CacheEntry] = field(default_factory=dict)
    reads: list[str] = field(default_factory=list)


def _warn(warnings, message):
    if message not in warnings:
        warnings.append(message)


# ---------------------------------------------------------------- read boundary


def _canonical(root):
    return Path(root).expanduser().resolve()


def _no_symlink_below(root, *parts):
    """True if no component strictly below the canonical root is a symlink."""
    cur = root
    for part in parts:
        cur = cur / part
        try:
            if cur.is_symlink():
                return False
        except OSError:
            return False
    return True


def _safe_source(root, *parts):
    """Return (path, ok). Refuses symlinks below root and paths resolving outside it."""
    if not _no_symlink_below(root, *parts):
        return None, False
    path = root.joinpath(*parts)
    try:
        resolved = path.resolve()
    except OSError:
        return None, False
    try:
        resolved.relative_to(root)
    except ValueError:
        return None, False
    return path, True


def _file_meta(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return FileMeta(st.st_mtime_ns, st.st_size, st.st_ino, st.st_dev)


def _read_json(root, cache, rel_parts, warnings, force, required_shape=None,
               label=None):
    """Read one allowlisted JSON source through the cache. Returns parsed data
    or None (missing or unreadable; a warning is recorded for real errors)."""
    label = label or "/".join(rel_parts)
    ok_path, ok = _safe_source(root, *rel_parts)
    if not ok:
        _warn(warnings, f"{label} is a symlink and was not read")
        return None
    path = ok_path
    if not path.exists():
        return None
    meta = _file_meta(path)
    rel = "/".join(rel_parts)
    if cache is not None and not force:
        entry = cache.entries.get(rel)
        if entry is not None and entry.meta == meta:
            return entry.raw
    if cache is not None:
        cache.reads.append(rel)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        _warn(warnings, f"{label} could not be read as JSON")
        return None
    if required_shape is not None and not isinstance(raw, required_shape):
        _warn(warnings, f"{label} has an unexpected structure")
        return None
    if cache is not None and meta is not None:
        cache.entries[rel] = CacheEntry(meta, raw)
    return raw


def _read_text(root, cache, rel_parts, warnings, force, label=None):
    label = label or "/".join(rel_parts)
    ok_path, ok = _safe_source(root, *rel_parts)
    if not ok:
        _warn(warnings, f"{label} is a symlink and was not read")
        return None
    path = ok_path
    if not path.exists():
        return None
    meta = _file_meta(path)
    rel = "/".join(rel_parts)
    if cache is not None and not force:
        entry = cache.entries.get(rel)
        if entry is not None and entry.meta == meta:
            return entry.raw
    if cache is not None:
        cache.reads.append(rel)
    try:
        raw = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        _warn(warnings, f"{label} could not be read")
        return None
    if cache is not None and meta is not None:
        cache.entries[rel] = CacheEntry(meta, raw)
    return raw


def _list_dir(root, sub, warnings):
    """Direct safe *.json / *.md entries of one allowlisted subdirectory."""
    ok_path, ok = _safe_source(root, sub)
    if not ok:
        _warn(warnings, f"{sub}/ is a symlink and was not read")
        return []
    path = ok_path
    if not path.is_dir():
        return []
    try:
        names = sorted(p.name for p in path.iterdir())
    except OSError:
        _warn(warnings, f"{sub}/ could not be listed")
        return []
    return names


# ------------------------------------------------------------------- project.json


def _load_config(root, warnings):
    raw = _read_json(root, None, ("project.json",), warnings, True)
    if raw is None:
        _warn(warnings, "project.json is missing or unreadable")
        return None
    if not isinstance(raw, dict):
        _warn(warnings, "project.json is not a JSON object")
        return None
    title = raw.get("title")
    target = raw.get("target_words")
    if "title" in raw and not isinstance(title, str):
        _warn(warnings, "project.json has invalid required fields")
        return None
    if "target_words" in raw and (isinstance(target, bool) or not isinstance(target, int)
                                  or target < 0):
        _warn(warnings, "project.json has invalid required fields")
        return None
    return ProjectInfo(title if isinstance(title, str) else DEFAULT_TITLE,
                       target if isinstance(target, int) and not isinstance(target, bool)
                       else DEFAULT_TARGET)


# --------------------------------------------------------------------- scenes.json


def _load_scenes(root, cache, force, warnings):
    raw = _read_json(root, cache, ("scenes.json",), warnings, force)
    if raw is None:
        return []
    if not isinstance(raw, list):
        _warn(warnings, "scenes.json is not a JSON list")
        return []
    rows, seen = [], set()
    for card in raw:
        if not isinstance(card, dict):
            _warn(warnings, "scenes.json: skipped a card that is not an object")
            continue
        sid = card.get("id")
        if not isinstance(sid, str) or not _ID_RE.match(sid):
            _warn(warnings, "scenes.json: skipped a card with an invalid id")
            continue
        if sid in seen:
            _warn(warnings, f"scenes.json: duplicate scene {sid}; kept the first")
            continue
        seen.add(sid)
        chapter = card.get("chapter")
        chapter = str(chapter) if isinstance(chapter, (int, str)) and \
            not isinstance(chapter, bool) else ""
        title = card.get("title") if isinstance(card.get("title"), str) else ""
        status = card.get("status") if isinstance(card.get("status"), str) else ""
        target = card.get("target_words")
        target = target if isinstance(target, int) and not isinstance(target, bool) else 0
        group = f"Chapter {chapter}" if chapter else "Current scenes"
        rows.append(SceneRow(sid, sid, chapter, title, status, target, group))
    return rows


# --------------------------------------------------------------------- trees/*.json


def _parse_history(entries, warnings, label, nid):
    out = []
    if entries is None:
        return out
    if not isinstance(entries, list):
        _warn(warnings, f"{label}: node {nid} has invalid history")
        return out
    for h in entries:
        if isinstance(h, dict) and all(isinstance(h.get(k), str) for k in ("time", "by", "text")):
            out.append({"time": h["time"], "by": h["by"], "text": h["text"]})
        else:
            _warn(warnings, f"{label}: node {nid} has an invalid history entry")
    return out


def _parse_node(nid, rec, warnings, label):
    if not isinstance(rec, dict):
        _warn(warnings, f"{label}: skipped invalid saved-node record")
        return None
    if rec.get("id") != nid:
        _warn(warnings, f"{label}: skipped a saved node with an invalid id")
        return None
    parent = rec.get("parent")
    if parent is not None and not isinstance(parent, str):
        _warn(warnings, f"{label}: node {nid} has an invalid parent reference")
        return None
    text = rec.get("text")
    if not isinstance(text, str):
        _warn(warnings, f"{label}: node {nid} has invalid text")
        return None
    sep = rec.get("sep", "\n\n")
    if not isinstance(sep, str):
        _warn(warnings, f"{label}: node {nid} has an invalid separator")
        return None
    info = NodeInfo(id=nid, parent=parent, text=text, sep=sep,
                    word_count=words(text),
                    history=_parse_history(rec.get("history"), warnings, label, nid))
    for name in ("source", "model", "created", "steer"):
        value = rec.get(name)
        setattr(info, name, value if isinstance(value, str) else None)
    for name in ("ended", "trimmed"):
        value = rec.get(name)
        setattr(info, name, value if isinstance(value, bool) else None)
    return info


def _link_ok(nodes, start):
    """Ancestors of `start` all exist and terminate without a cycle."""
    seen = set()
    cur = nodes[start].parent
    while cur is not None:
        if cur in seen:
            return False
        seen.add(cur)
        nxt = nodes.get(cur)
        if nxt is None:
            return False
        cur = nxt.parent
    return True


def _load_tree(root, stem, global_warnings, cache, force):
    label = f"trees/{stem}.json"
    warnings: list[str] = []
    raw = _read_json(root, cache, ("trees", f"{stem}.json"), warnings, force)
    view = TreeView(id=stem)
    if raw is None:
        view.broken = True
        global_warnings.extend(warnings)
        return view
    if not isinstance(raw, dict):
        _warn(warnings, f"{label} has an unexpected structure")
        view.broken = True
        return view
    node_map = raw.get("nodes")
    if not isinstance(node_map, dict):
        _warn(warnings, f"{label} has an unexpected structure")
        view.broken = True
        return view
    for nid, rec in node_map.items():
        info = _parse_node(nid, rec, warnings, label)
        if info is None:
            continue
        view.nodes[nid] = info
        view.order.append(nid)
    for info in view.nodes.values():
        info.link_ok = _link_ok(view.nodes, info.id)
        if info.parent in view.nodes:
            view.nodes[info.parent].children.append(info.id)
    for info in view.nodes.values():
        info.children.sort(key=_node_sort_key)
    head = raw.get("head")
    if head is not None and not isinstance(head, str):
        _warn(warnings, f"{label} has an invalid head reference; treated as no head")
        head = None
    view.head = head
    if head is None:
        view.active_text = ""
        view.active_words = 0
        view.active_ids = []
    elif head is not None:
        if head not in view.nodes:
            _warn(warnings, f"{label}: head references a missing node; "
                            "active text is unavailable")
        elif not view.nodes[head].link_ok:
            _warn(warnings, f"{label}: active chain is broken; "
                            "active text is unavailable")
        else:
            t = Tree.__new__(Tree)
            t.d = {"nodes": {nid: {"id": nid, "parent": info.parent, "text": info.text,
                                   "sep": info.sep}
                             for nid, info in view.nodes.items()},
                   "head": head, "counter": len(view.nodes)}
            view.active_ids = t.chain(head)
            for nid in view.active_ids:
                view.nodes[nid].on_active_path = True
            view.active_text = t.text(head)
            view.active_words = words(view.active_text)
    global_warnings.extend(warnings)
    view.warnings = list(warnings)
    return view


def _node_sort_key(nid):
    m = re.match(r"n(\d+)\Z", nid)
    return (0, int(m.group(1))) if m else (1, nid)


def _load_trees(root, warnings, cache, force):
    """All safe, direct trees/*.json stems, sorted by ID."""
    trees = {}
    names = _list_dir(root, "trees", warnings)
    for name in names:
        if not name.endswith(".json"):
            continue
        stem = name[:-5]
        if not _ID_RE.match(stem):
            _warn(warnings, f"trees/{name} has an unsafe id and was skipped")
            continue
        _ok, safe = _safe_source(root, "trees", name)
        if not safe:
            _warn(warnings, f"trees/{name} is a symlink and was skipped")
            continue
        trees[stem] = _load_tree(root, stem, warnings, cache, force)
    return trees


def load_snapshot(root, cache=None, force=False):
    """Load one sanitized snapshot. Returns LoadResult(snapshot=None, warnings)
    for invalid required configuration; optional sources degrade to warnings."""
    warnings: list[str] = []
    canon = _canonical(root)
    project = _load_config(canon, warnings)
    if project is None:
        return LoadResult(None, warnings)
    scenes = _load_scenes(canon, cache, force, warnings)
    trees = _load_trees(canon, warnings, cache, force)
    notes = _load_notes(canon, cache, force, warnings)
    actual, complete = 0, True
    for row in scenes:
        view = trees.get(row.id)
        if view is None or view.broken:
            complete = False
            continue
        if view.active_words is None:
            complete = False
            continue
        actual += view.active_words
    snap = Snapshot(project=project, scenes=scenes, trees=trees, notes=notes,
                    actual_words=actual, words_complete=complete,
                    warnings=list(warnings))
    return LoadResult(snap, warnings)


# ------------------------------------------------------------------------ notes


def _load_notes(root, cache, force, warnings):
    notes = NotesView()
    notes.bible = _read_text(root, cache, ("bible.md",), warnings, force)
    notes.state = _read_text(root, cache, ("state.md",), warnings, force)
    notes.summaries = _load_summaries(root, cache, force, warnings)
    notes.checks = _load_report_dir(root, "checks", cache, force, warnings)
    notes.critiques = _load_report_dir(root, "critiques", cache, force, warnings)
    return notes


def _load_summaries(root, cache, force, warnings):
    raw = _read_json(root, cache, ("summaries.json",), warnings, force)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        _warn(warnings, "summaries.json has an unexpected structure")
        return None
    scenes_raw = raw.get("scenes", {})
    arcs_raw = raw.get("arcs", [])
    if not isinstance(scenes_raw, dict) or not isinstance(arcs_raw, list):
        _warn(warnings, "summaries.json has an unexpected structure")
        return None
    view = SummariesView()
    for sid, rec in scenes_raw.items():
        if not isinstance(sid, str) or not isinstance(rec, dict):
            _warn(warnings, "summaries.json: skipped an invalid scene summary")
            continue
        view.scenes[sid] = SummaryEntry(
            scene_id=sid,
            detailed=rec.get("detailed") if isinstance(rec.get("detailed"), str) else None,
            brief=rec.get("brief") if isinstance(rec.get("brief"), str) else None,
            updated=rec.get("updated") if isinstance(rec.get("updated"), str) else None)
    for rec in arcs_raw:
        if not isinstance(rec, dict) or not isinstance(rec.get("from"), str) \
                or not isinstance(rec.get("to"), str) or not isinstance(rec.get("text"), str):
            _warn(warnings, "summaries.json: skipped an invalid arc summary")
            continue
        view.arcs.append(ArcEntry(
            from_id=rec["from"], to_id=rec["to"], text=rec["text"],
            updated=rec.get("updated") if isinstance(rec.get("updated"), str) else None))
    return view


def _load_report_dir(root, sub, cache, force, warnings):
    """All direct safe *.md reports (including backups), sorted by filename."""
    out = []
    for name in _list_dir(root, sub, warnings):
        if not name.endswith(".md"):
            continue
        text = _read_text(root, cache, (sub, name), warnings, force,
                          label=f"{sub}/{name}")
        if text is None:
            continue
        out.append(NoteFile(name, text))
    return out
