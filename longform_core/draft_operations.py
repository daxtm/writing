"""Qt-independent draft-loop operations shared by the CLI adapter and the GUI.

Extracted from commands.cmd_draft/pick_candidates (ADR-0007): plain-value
inputs, typed progress events, an injectable provider/cancellation token, and
stale-baseline guards before every save. No Qt imports and no terminal helpers:
prompt bytes, sampling, cleaning, node metadata, histories and file formats are
preserved exactly; the CLI keeps printing/transcript behavior in its adapter.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .api import Api, HttpErr, NoAnswerErr
from .cancel import Cancelled
from .config import SAMPLING_KEYS
from .lore import is_present, Lore, pov_name
from .prompt import build_writer_prompt, clean_continuation, format_card, writer_sampling
from .reader_model import _no_symlink_below
from .tree import Tree
from .utils import (FatalError, keep_lead, now, redact_text, write_text,
                    StreamRedactor)


class OpError(Exception):
    """User-correctable operation failure with a sanitized message.

    `stale` marks a detected external change (offer reload/retry, never
    overwrite); `soft` marks failures the CLI reports without exiting
    (e.g. "generation failed: ..."); `from_die` marks messages that a die()
    call already printed to stderr, so the CLI adapter must not print again."""

    def __init__(self, msg, stale=False, soft=False, from_die=False, collision=False):
        super().__init__(msg)
        self.stale = stale
        self.soft = soft
        self.from_die = from_die
        self.collision = collision


def _emit(events, kind, **payload):
    if events:
        events(dict({"type": kind}, **payload))


# --------------------------------------------------------------- session

def _project_of(root):
    from .project import Project
    try:
        return Project(root)
    except FatalError as e:
        raise OpError(str(e.msg), from_die=True) from None


def _session(root, scene_id):
    """Project, scenes, index and card for a scene id; sanitized failures."""
    p = _project_of(root)
    try:
        scenes = p.scenes()
    except FatalError as e:
        raise OpError(str(e.msg), from_die=True) from None
    if not scenes:
        raise OpError("no scenes (run: scenes)")
    idx = next((i for i, s in enumerate(scenes) if s.get("id") == scene_id), None)
    if idx is None:
        raise OpError(f"no scene with id {scene_id}")
    return p, scenes, idx, scenes[idx]


def _tree(p, scene_id):
    try:
        return Tree(p, scene_id)
    except FatalError as e:
        raise OpError(str(e.msg), from_die=True) from None


def _lore(p, scenes):
    try:
        return Lore(p, scenes)
    except FatalError as e:
        raise OpError(str(e.msg), from_die=True) from None


def _preset(p):
    try:
        return p.preset()
    except FatalError as e:
        raise OpError(str(e.msg), from_die=True) from None


def _provider(p, factory):
    try:
        return (factory or (lambda pp: Api(pp)))(p)
    except FatalError as e:
        raise OpError(str(e.msg), from_die=True) from None


def credential_state(cfg, session=False):
    """Availability-only credential facts (ADR-0011): effective source
    ('session'|'project'|'environment'|'missing') and booleans; never a key
    value. `session` is the GUI's window-override availability input."""
    key = str(cfg.get("api_key") or "").strip()
    env = str(cfg.get("api_key_env") or "")
    env_set = bool(env) and bool(os.environ.get(env, "").strip())
    if session:
        source = "session"
    elif key:
        source = "project"
    elif env_set:
        source = "environment"
    else:
        source = "missing"
    return {"available": source != "missing", "source": source,
            "api_key_env": env, "inline_key": bool(key), "env_set": env_set}


def redaction_secrets(p, provider=None):
    """Every nonempty credential value this call knows (session, saved
    project, configured environment) for scrubbing echoes; provider objects
    built by the GUI window carry the full context in `secrets`."""
    vals = []
    for v in (getattr(provider, "secrets", None) or ()):
        if v and v not in vals:
            vals.append(v)
    key = str(p.cfg.get("api_key") or "").strip()
    env = str(p.cfg.get("api_key_env") or "")
    envval = os.environ.get(env, "").strip() if env else ""
    for v in (key, envval):
        if v and v not in vals:
            vals.append(v)
    return tuple(vals)


def scrub_credentials(p, text, provider=None):
    """Redact all known credential values from one text (errors, echoes)."""
    return redact_text(text or "", redaction_secrets(p, provider))


def _find_idx(scenes, scene_id):
    return next((i for i, s in enumerate(scenes) if s.get("id") == scene_id), None)


# ------------------------------------------------------------- baselines

def _read_bytes(path, key):
    try:
        return path.read_bytes() if path.exists() else None
    except OSError as e:
        raise OpError(f"{key} could not be read ({type(e).__name__})") from None


def _preset_key(p):
    path = p.preset_path()
    try:
        return str(path.relative_to(p.root))
    except ValueError:
        return str(path)


def baseline_keys(p, scene_ids):
    """Relative source names whose exact bytes feed the prompt or are written."""
    keys = ["project.json", "scenes.json", "summaries.json", "bible.md",
            "state.md", "limits.json", "calib.json", "lorebooks.json",
            _preset_key(p), "lorebooks/*"]
    for sid in scene_ids:
        keys.append(f"trees/{sid}.json")
    return keys


def _capture(p, keys):
    out = {}
    for key in keys:
        if key == "lorebooks/*":
            d = p.f("lorebooks")
            out[key] = tuple(sorted(x.name for x in d.iterdir())) if d.is_dir() else ()
            continue
        path = Path(key) if os.path.isabs(key) else p.f(key)
        out[key] = _read_bytes(path, key)
    return out


def _advance(p, baseline, key):
    """Record an operation-owned change (our own writes/hidden bookkeeping)."""
    if key in baseline:
        path = Path(key) if os.path.isabs(key) else p.f(key)
        baseline[key] = _read_bytes(path, key)


def _stale_check(p, baseline):
    current = _capture(p, list(baseline))
    changed = sorted(k for k in baseline if current[k] != baseline[k])
    if changed:
        raise OpError("saved sources changed on disk since the operation "
                      "started (" + ", ".join(changed) + "); reload and retry "
                      "instead of overwriting", stale=True)
    return current


def _check_tree_writable(p, scene_id):
    if not _no_symlink_below(p.root, "trees", f"{scene_id}.json"):
        raise OpError(f"trees/{scene_id}.json is a symlink; refusing to write")


def _save_tree(tree, p, scene_id, baseline):
    _check_tree_writable(p, scene_id)
    _stale_check(p, baseline)
    tree.save()
    _advance(p, baseline, f"trees/{scene_id}.json")


def _save_scenes(scenes, p, baseline):
    _stale_check(p, {"scenes.json": baseline["scenes.json"]})
    p.save_scenes(scenes)
    _advance(p, baseline, "scenes.json")


# ------------------------------------------------------------ generation

@dataclass
class GenerateResult:
    saved: list                 # candidate node ids, display order
    streamed: bool = False      # count == 1: deltas went to the preview
    over: bool = False          # over budget: no call was made
    report: dict = field(default_factory=dict)
    prompt: str = ""
    params: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)
    ignored: list = field(default_factory=list)
    parent: object = None       # captured head/parent all candidates share
    steer: str = ""
    passage_words: int = 0
    shortfall: int = 0          # requested count minus completed responses


def generate_candidates(root, scene_id, *, count=1, parent=None, steer=None,
                        passage_words=None, provider_factory=None, token=None,
                        events=None, preview_events=None):
    """Generate `count` candidate passages as siblings of `parent` (default head).

    Cleaning, cutoff handling and node metadata match the CLI byte-for-byte.
    A failed, cancelled or empty cleaned response creates no node; complete
    candidates saved earlier stay saved. Raises OpError (stale/soft) or
    Cancelled; never moves the head.

    `preview_events` (ADR-0012), when given, is called with the submission
    slot index i and must return that candidate's live answer subscriber;
    slot ids are assigned before submission, so preview candidate_id stays
    stable regardless of completion order. Without it the legacy single-
    stream/CLI delta events are unchanged and no preview events are emitted."""
    count = max(1, int(count))
    pf = None if preview_events is None else preview_factory(events,
                                                             preview_events)
    p, scenes, idx, sc = _session(root, scene_id)
    tree = _tree(p, scene_id)
    head0 = tree.head if parent is None else parent
    rc = p.cfg["roles"]["writer"]
    steer = tree.d.get("steer", "") if steer is None else steer
    passage_words = int(passage_words or rc.get("passage_words", 220))
    lore = _lore(p, scenes)
    baseline = _capture(p, baseline_keys(p, [scene_id] + ([scenes[idx - 1]["id"]] if idx > 0 else [])))
    if token:
        token.check()
    try:
        prompt, params, extra, ignored, rep = build_writer_prompt(
            p, _preset(p), lore, scenes, idx, tree, steer, passage_words)
    except FatalError as e:
        raise OpError(str(e.msg), from_die=True) from None
    except OSError as e:
        raise OpError(f"project source could not be read ({type(e).__name__})") from None
    for note in rep["notes"]:
        _emit(events, "note", text=note)
    if rep["over"]:
        _emit(events, "over_budget")
        return GenerateResult(saved=[], over=True, report=rep, prompt=prompt,
                              params=params, extra=extra, parent=head0,
                              steer=steer, passage_words=passage_words)
    provider = _provider(p, provider_factory)
    meta = {"scene": sc["id"], "head": head0, "lorebooks": lore.active(),
            "present": sc.get("characters") or [], "char": rep["char"], "steer": steer}

    def one(i=None):
        return provider.complete("writer", prompt, params, extra, meta=meta,
                                 token=token,
                                 preview_events=None if pf is None else pf(i))

    try:
        if count == 1:
            _emit(events, "stream_start")
            sub = None if pf is None else pf(0)
            if sub is not None:
                # ADR-0012: the subscriber receives the answer preview; the
                # legacy CLI delta channel is not duplicated on top of it.
                results = [provider.complete(
                    "writer", prompt, params, extra, meta=meta, token=token,
                    preview_events=sub)]
                rest = ""
            else:
                red = StreamRedactor(redaction_secrets(p, provider))
                results = [provider.complete("writer", prompt, params, extra,
                                             stream_cb=(lambda t: _emit(events, "delta",
                                                                        text=red.feed(t))) if events else None,
                                             meta=meta, token=token,
                                             on_retry_event=(lambda kind: _emit(events, kind)) if events else None)]
                rest = red.flush()
                if rest and events:
                    _emit(events, "delta", text=rest)
            _emit(events, "stream_end")
            streamed = True
        else:
            _emit(events, "progress",
                  msg=f"generating {count} candidates (max_parallel {p.cfg['max_parallel']})...")
            results = provider.many(one, count, token=token,
                                    on_event=(lambda ev: _emit_raw(events, ev)) if events else None,
                                    indexed=(lambda i: (lambda: one(i)))
                                    if pf is not None else None)
            streamed = False
    except Cancelled:
        raise
    except (HttpErr, NoAnswerErr, httpx.HTTPError, FatalError) as e:
        raise OpError(f"generation failed: {scrub_credentials(p, str(e), provider)}",
                      soft=True) from None
    _advance(p, baseline, "calib.json")   # our own calls may record calibration
    ids = []
    secrets = redaction_secrets(p, provider)
    for text, finish, _ in results:
        if token:
            token.check()
        clean, ended, trimmed = clean_continuation(redact_text(text, secrets), finish, rep["continuing"])
        if not clean.strip():
            _emit(events, "skipped_empty")
            continue
        nid = tree.add(head0, clean, source="model", sep="" if rep["continuing"] else "\n\n",
                       model=rc["model"], steer=steer, ended=ended, trimmed=trimmed,
                       finish=finish, lorebooks=lore.active(),
                       present=sc.get("characters") or [],
                       absent=lore.absent_mentions(sc, clean))
        _save_tree(tree, p, scene_id, baseline)
        ids.append(nid)
        _emit(events, "candidate_saved", nid=nid)
    if len(results) < count:
        _emit(events, "shortfall", got=len(results), wanted=count)
    return GenerateResult(saved=ids, streamed=streamed, report=rep, prompt=prompt,
                          params=params, extra=extra, ignored=ignored,
                          parent=head0, steer=steer, passage_words=passage_words,
                          shortfall=max(0, count - len(results)))


def _emit_raw(events, payload):
    if events:
        events(dict(payload))


def preview_factory(events, preview_events):
    """Common ADR-0012 forwarding: bind each slot's subscriber to its candidate
    slot before submission. With an events channel, each provider preview
    event is re-emitted on it tagged with candidate_id=i+1 (the queued worker
    channel pairs it with the operation id); otherwise the subscriber receives
    the provider event directly."""
    def factory(i):
        sub = preview_events(i) if preview_events is not None else None
        if sub is None:
            return None
        if events is None:
            return sub
        c = i + 1

        def fwd(ev, c=c):
            d = {k: v for k, v in ev.items() if k != "type"}
            _emit(events, ev.get("type"), candidate_id=c, **d)
        return fwd
    return factory


PREVIEW_TYPES = ("preview_start", "preview_delta", "preview_reset",
                 "preview_complete")


def accept_candidate(root, scene_id, nid, *, token=None, events=None):
    """Accept a saved candidate: head moves to it (choosing its ancestor path),
    planned becomes drafting; nothing is deleted."""
    p, scenes, idx, sc = _session(root, scene_id)
    tree = _tree(p, scene_id)
    if nid not in tree.d["nodes"]:
        raise OpError(f"no such node: {nid}")
    baseline = _capture(p, baseline_keys(p, [scene_id]))
    if token:
        token.check()
    tree.head = nid
    _save_tree(tree, p, scene_id, baseline)
    status_changed = False
    if sc.get("status") == "planned":
        sc["status"] = "drafting"
        _save_scenes(scenes, p, baseline)
        status_changed = True
    _emit(events, "accepted", nid=nid)
    return {"head": nid, "ended": bool(tree.node(nid).get("ended")),
            "status": sc["status"], "status_changed": status_changed}


def delete_leaf(root, scene_id, nid, *, token=None, events=None):
    """Delete an eligible leaf (a deleted head leaf moves head to its parent);
    a node with children is refused without tree changes."""
    p, scenes, idx, sc = _session(root, scene_id)
    tree = _tree(p, scene_id)
    if nid not in tree.d["nodes"]:
        raise OpError(f"no such node: {nid}")
    baseline = _capture(p, baseline_keys(p, [scene_id]))
    if token:
        token.check()
    if not tree.delete(nid):
        raise OpError(f"node {nid} has children; not deleted", soft=True)
    _save_tree(tree, p, scene_id, baseline)
    _emit(events, "deleted", nid=nid)
    return {"deleted": nid, "head": tree.head}


def set_cast(root, scene_id, names, *, token=None):
    """Set the characters physically present in the scene (CLI `who`)."""
    p, scenes, idx, sc = _session(root, scene_id)
    names = [n for n in (names or []) if n]
    baseline = _capture(p, ["scenes.json"])
    if token:
        token.check()
    if names:
        sc["characters"] = names
        _save_scenes(scenes, p, baseline)
    return {"scene": scene_id, "cast": sc.get("characters") or []}


def set_pov(root, scene_id, name, *, token=None):
    """Set the POV character ({{char}}) for the scene (CLI `pov`)."""
    p, scenes, idx, sc = _session(root, scene_id)
    baseline = _capture(p, ["scenes.json"])
    if token:
        token.check()
    if name:
        sc["pov"] = name
        _save_scenes(scenes, p, baseline)
    return {"scene": scene_id, "pov": sc.get("pov", ""), "char": pov_name(sc)}


def mark_done(root, scene_id, *, token=None):
    """Mark the scene done; continuity update stays an explicit later step."""
    p, scenes, idx, sc = _session(root, scene_id)
    baseline = _capture(p, ["scenes.json"])
    if token:
        token.check()
    sc["status"] = "done"
    _save_scenes(scenes, p, baseline)
    return {"status": "done", "scene": scene_id,
            "hint": f"scene {scene_id} done. next step: update-state {p.root} --scene {scene_id}"}


def append_manual(root, scene_id, text, *, token=None, events=None):
    """Append a manual passage after head as a new paragraph (CLI `w`).

    Empty input is a no-op; a saved passage moves head and planned becomes
    drafting."""
    p, scenes, idx, sc = _session(root, scene_id)
    text = (text or "").strip()
    if not text:
        return {"added": None, "head": None}
    tree = _tree(p, scene_id)
    baseline = _capture(p, baseline_keys(p, [scene_id]))
    if token:
        token.check()
    tree.head = tree.add(tree.head, text, source="user", sep="\n\n")
    _save_tree(tree, p, scene_id, baseline)
    status_changed = False
    if sc.get("status") == "planned":
        sc["status"] = "drafting"
        _save_scenes(scenes, p, baseline)
        status_changed = True
    _emit(events, "added", nid=tree.head)
    return {"added": tree.head, "head": tree.head, "status_changed": status_changed}


def edit_head(root, scene_id, new_text, *, token=None, events=None):
    """Edit the head passage in place (CLI `e`).

    Preserves continuation-leading whitespace (`keep_lead`), records
    time/old-text/by=user-edit history; empty or unchanged input is a no-op."""
    from .utils import keep_lead

    p, scenes, idx, sc = _session(root, scene_id)
    tree = _tree(p, scene_id)
    if not tree.head:
        raise OpError("nothing to edit", soft=True)
    baseline = _capture(p, baseline_keys(p, [scene_id]))
    if token:
        token.check()
    n = tree.node(tree.head)
    old = n["text"]
    new = (new_text or "").rstrip()
    if n.get("sep") == "":
        new = keep_lead(old, new)
    if not new.strip() or new == old:
        return {"changed": False, "old": old, "new": old, "head": tree.head}
    n["history"].append({"time": now(), "text": old, "by": "user-edit"})
    n["text"] = new
    _save_tree(tree, p, scene_id, baseline)
    _emit(events, "edited", nid=tree.head)
    return {"changed": True, "old": old, "new": new, "head": tree.head}


def rewind(root, scene_id, *, token=None, events=None):
    """Move head to its parent without deleting text (CLI `r`)."""
    p, scenes, idx, sc = _session(root, scene_id)
    tree = _tree(p, scene_id)
    if not tree.head:
        return {"head": None}
    baseline = _capture(p, baseline_keys(p, [scene_id]))
    if token:
        token.check()
    tree.head = tree.node(tree.head)["parent"]
    _save_tree(tree, p, scene_id, baseline)
    _emit(events, "rewound", head=tree.head)
    return {"head": tree.head}


def jump(root, scene_id, nid, *, token=None, events=None):
    """Explicitly switch the accepted path to a saved node (CLI `j ID`)."""
    p, scenes, idx, sc = _session(root, scene_id)
    tree = _tree(p, scene_id)
    if nid not in tree.d["nodes"]:
        raise OpError("no such node", soft=True)
    baseline = _capture(p, baseline_keys(p, [scene_id]))
    if token:
        token.check()
    tree.head = nid
    _save_tree(tree, p, scene_id, baseline)
    _emit(events, "jumped", head=nid)
    return {"head": nid}


def scene_card(root, scene_id):
    """Read-only scene card and fields for the desktop Scene pane."""
    p, scenes, idx, sc = _session(root, scene_id)
    return {"card": format_card(sc), "pov": sc.get("pov", ""),
            "cast": ", ".join(sc.get("characters") or []),
            "status": sc.get("status", ""),
            "target_words": sc.get("target_words", 0),
            "char": pov_name(sc)}


def scene_overview(root):
    """Ordered [{id,status,title}] for Next unfinished / explicit reopen."""
    p = _project_of(root)
    scenes = _scenes_or_error(p)
    return [{"id": s["id"], "status": s.get("status", ""), "title": s.get("title", "")}
            for s in scenes]


# ------------------------------------------------------------------- lore

def _lore_target(root, scene_id, k):
    p, scenes, idx, sc = _session(root, scene_id)
    lore = _lore(p, scenes)
    books = lore.books()
    if not isinstance(k, int) or not 1 <= k <= len(books):
        raise OpError("no such lorebook number", soft=True)
    return lore, books[k - 1], p, scenes


def _save_registry(lore, p, baseline):
    _stale_check(p, {"lorebooks.json": baseline["lorebooks.json"]})
    lore.save()
    _advance(p, baseline, "lorebooks.json")


def lore_rows(root, scene_id):
    """Every discovered book with on/kind/character/role/entries (CLI lb list)."""
    p, scenes, idx, sc = _session(root, scene_id)
    lore = _lore(p, scenes)
    present = sc.get("characters") or []
    pov = pov_name(sc)
    rows = []
    for k, (fname, meta) in enumerate(lore.books(), 1):
        role, who = "", ""
        if meta.get("kind") == "character":
            name = lore.char_name(fname, meta)
            al = meta.get("aliases", [])
            if is_present(name, al, [pov]):
                role = "POV"
            elif is_present(name, al, present):
                role = "present"
            else:
                role = "not in scene"
            who = name + (f" ({', '.join(al)})" if al else "")
        rows.append({"n": k, "file": fname, "on": bool(meta.get("on")),
                     "kind": meta.get("kind", "world"), "who": who, "role": role,
                     "entries": len(lore.entries(fname))})
    return rows


def lore_toggle(root, scene_id, numbers, *, token=None):
    """Toggle lorebooks by 1-based display numbers (CLI lb N [N ...])."""
    p, scenes, idx, sc = _session(root, scene_id)
    lore = _lore(p, scenes)
    books = lore.books()
    valid = [int(x) for x in numbers if isinstance(x, int) and 1 <= x <= len(books)]
    if not valid:
        raise OpError("no such lorebook number", soft=True)
    baseline = _capture(p, ["lorebooks.json"])
    if token:
        token.check()
    for k in valid:
        books[k - 1][1]["on"] = not books[k - 1][1].get("on")
    _save_registry(lore, p, baseline)
    return {"scene": scene_id, "rows": lore_rows(root, scene_id)}


def lore_set_all(root, scene_id, on, *, token=None):
    """Switch every lorebook on/off (CLI lb all on|off)."""
    p, scenes, idx, sc = _session(root, scene_id)
    lore = _lore(p, scenes)
    books = lore.books()
    if not books:
        raise OpError("no lorebooks to switch", soft=True)
    baseline = _capture(p, ["lorebooks.json"])
    if token:
        token.check()
    for _, meta in books:
        meta["on"] = bool(on)
    _save_registry(lore, p, baseline)
    return {"scene": scene_id, "rows": lore_rows(root, scene_id)}


def lore_set_char(root, scene_id, k, name, *, token=None):
    """Mark book k as a character lorebook for NAME (CLI lb N char NAME)."""
    lore, (fname, meta), p, scenes = _lore_target(root, scene_id, k)
    if not name:
        raise OpError("usage: lb N char NAME", soft=True)
    baseline = _capture(p, ["lorebooks.json"])
    if token:
        token.check()
    meta["kind"] = "character"
    meta["character"] = name
    _save_registry(lore, p, baseline)
    return {"scene": scene_id, "rows": lore_rows(root, scene_id)}


def lore_set_aliases(root, scene_id, k, names, *, token=None):
    """Set other names the character goes by (CLI lb N alias A, B)."""
    lore, (fname, meta), p, scenes = _lore_target(root, scene_id, k)
    baseline = _capture(p, ["lorebooks.json"])
    if token:
        token.check()
    meta["aliases"] = [a.strip() for a in (names or []) if a.strip()]
    _save_registry(lore, p, baseline)
    return {"scene": scene_id, "rows": lore_rows(root, scene_id)}


def lore_set_world(root, scene_id, k, *, token=None):
    """Mark book k as a world lorebook (CLI lb N world)."""
    lore, (fname, meta), p, scenes = _lore_target(root, scene_id, k)
    baseline = _capture(p, ["lorebooks.json"])
    if token:
        token.check()
    meta["kind"] = "world"
    _save_registry(lore, p, baseline)
    return {"scene": scene_id, "rows": lore_rows(root, scene_id)}


def lore_import(root, src, scene_id=None, replace=False, *, token=None, events=None):
    """Import an external World Info/character-book file through the existing
    parser/discovery: unchanged bytes into lorebooks/, existing classification,
    registry metadata preserved on Replace, nothing written when invalid."""
    import base64
    from .lore import card_png_json, parse_book_data

    p = _project_of(root)
    scenes = _scenes_or_error(p)
    src = Path(src)
    if not src.is_file():
        raise OpError(f"not a file: {src.name}", soft=True)
    name = src.name
    if not name.lower().endswith((".json", ".png")):
        raise OpError(f"{name}: unsupported lorebook file type (use .json or .png)",
                      soft=True)
    try:
        data = src.read_bytes()
    except OSError as e:
        raise OpError(f"{name} could not be read ({type(e).__name__})", soft=True) from None
    if name.lower().endswith(".png"):
        d = card_png_json(data)
        if d is None:
            raise OpError(f"{name}: no character card data found in this PNG", soft=True)
        card_name, entries = parse_book_data(d, src.stem)
    else:
        try:
            d = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise OpError(f"{name} is not valid JSON: {e}", soft=True) from None
        if not isinstance(d, (dict, list)):
            raise OpError(f"{name} is not a World Info export or character card",
                          soft=True)
        card_name, entries = parse_book_data(d, src.stem)
    if not _no_symlink_below(p.root, "lorebooks", name):
        raise OpError(f"lorebooks/{name} is a symlink; refusing to write", soft=True)
    dest = p.f("lorebooks", name)
    baseline = _capture(p, ["lorebooks.json", "lorebooks/*", f"lorebooks/{name}"])
    if token:
        token.check()
    existed = baseline[f"lorebooks/{name}"] is not None
    if existed and not replace:
        raise OpError(f"destination exists: lorebooks/{name} — choose Replace "
                      "or Cancel", soft=True, collision=True)
    _stale_check(p, baseline)   # unchanged source/destination baselines
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    except OSError as e:
        raise OpError(f"lorebooks/{name} could not be written "
                      f"({type(e).__name__})", soft=True) from None
    _advance(p, baseline, f"lorebooks/{name}")
    _advance(p, baseline, "lorebooks/*")
    lore = _lore(p, scenes)   # existing discovery/classification; known names keep their registry metadata
    _advance(p, baseline, "lorebooks.json")
    _emit(events, "imported", name=name)
    out = {"imported": name, "card_name": card_name, "entries": len(entries),
           "replaced": existed}
    if scene_id:
        out["scene"] = scene_id
        out["rows"] = lore_rows(root, scene_id)
    return out


# ------------------------------------------------------ session/inspection

def session_info(root, scene_id=None, *, session=False):
    """Plain session defaults and prerequisite/warning report (no calls).

    `warnings` holds ignored project sampler keys and earlier-scene warnings;
    `sampler_warnings` holds preset sampler notes. The CLI prints warnings,
    then its preset line, then sampler warnings — keep that order when
    adapting; the GUI shows both lists combined. `session` is the GUI's
    window-credential availability input (ADR-0011); only availability facts
    are reported, never a key value."""
    info = {"swipes": 1, "passage_words": 220, "model": "", "preset_found": False,
            "creds_ok": False, "api_key_env": "", "warnings": [],
            "sampler_warnings": [], "scene_ok": False}
    p = _project_of(root)
    scenes = _scenes_or_error(p)
    rc = p.cfg["roles"]["writer"]
    info.update(swipes=max(1, int(rc.get("swipes", 1))),
                passage_words=int(rc.get("passage_words", 220)), model=rc["model"])
    creds = credential_state(p.cfg, session=session)
    info.update(api_key_env=creds["api_key_env"], cred_source=creds["source"])
    info["creds_ok"] = creds["available"]
    stale = [k for k in SAMPLING_KEYS if k in rc]
    if stale:
        info["warnings"].append("writer keys " + ", ".join(stale)
                                + " in project.json are ignored: writer samplers come from the preset")
    sampler_notes = []
    try:
        preset = p.preset()
    except FatalError as e:
        info["warnings"].append(str(e.msg))
    else:
        info["preset_found"] = True
        _params, _extra, ignored = writer_sampling(preset, lambda x, name=None: x)
        if ignored:
            sampler_notes.append("preset samplers with no Featherless parameter (not sent): " + ", ".join(ignored))
        if preset["preset"].get("temperature_last"):
            sampler_notes.append("preset has temperature_last; Featherless doesn't expose sampler order, "
                                 "so the server's default order applies")
    if scene_id is not None:
        idx = _find_idx(scenes, scene_id)
        if idx is not None:
            info["scene_ok"] = True
            try:
                sums = p.summaries()["scenes"]
            except FatalError as e:
                raise OpError(str(e.msg), from_die=True) from None
            for s in scenes[:idx]:
                if s.get("status") != "done":
                    info["warnings"].append(f"earlier scene {s['id']} is not marked done")
                elif s["id"] not in sums:
                    info["warnings"].append(f"earlier scene {s['id']} has no summary/state update "
                                            f"(run: update-state {p.root} --scene {s['id']})")
    info["sampler_warnings"] = sampler_notes
    return info


def _scenes_or_error(p):
    try:
        return p.scenes()
    except FatalError as e:
        raise OpError(str(e.msg), from_die=True) from None


def prepare_report(root, scene_id, *, steer=None, passage_words=None):
    """Exact next-call prompt/params/extra/report for captured inputs (no call)."""
    p, scenes, idx, sc = _session(root, scene_id)
    tree = _tree(p, scene_id)
    rc = p.cfg["roles"]["writer"]
    steer = tree.d.get("steer", "") if steer is None else steer
    passage_words = int(passage_words or rc.get("passage_words", 220))
    lore = _lore(p, scenes)
    try:
        prompt, params, extra, ignored, rep = build_writer_prompt(
            p, _preset(p), lore, scenes, idx, tree, steer, passage_words)
    except FatalError as e:
        raise OpError(str(e.msg), from_die=True) from None
    except OSError as e:
        raise OpError(f"project source could not be read ({type(e).__name__})") from None
    return {"prompt": prompt, "params": params, "extra": extra,
            "ignored": ignored, "report": rep}


def dump_prompt(root, scene_id, *, steer=None, passage_words=None, path=None):
    """Write the exact prompt bytes to last_prompt.txt (CLI `cp` parity)."""
    p, scenes, idx, sc = _session(root, scene_id)
    prep = prepare_report(root, scene_id, steer=steer, passage_words=passage_words)
    out = Path(path) if path else p.f("last_prompt.txt")
    write_text(out, prep["prompt"])
    return dict(prep, path=str(out))
