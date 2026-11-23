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
from .lore import Lore
from .prompt import build_writer_prompt, clean_continuation, print_report, writer_sampling
from .reader_model import _no_symlink_below
from .tree import Tree
from .utils import FatalError, write_text


class OpError(Exception):
    """User-correctable operation failure with a sanitized message.

    `stale` marks a detected external change (offer reload/retry, never
    overwrite); `soft` marks failures the CLI reports without exiting
    (e.g. "generation failed: ..."); `from_die` marks messages that a die()
    call already printed to stderr, so the CLI adapter must not print again."""

    def __init__(self, msg, stale=False, soft=False, from_die=False):
        super().__init__(msg)
        self.stale = stale
        self.soft = soft
        self.from_die = from_die


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
                        events=None):
    """Generate `count` candidate passages as siblings of `parent` (default head).

    Cleaning, cutoff handling and node metadata match the CLI byte-for-byte.
    A failed, cancelled or empty cleaned response creates no node; complete
    candidates saved earlier stay saved. Raises OpError (stale/soft) or
    Cancelled; never moves the head."""
    count = max(1, int(count))
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

    def one():
        return provider.complete("writer", prompt, params, extra, meta=meta, token=token)

    try:
        if count == 1:
            _emit(events, "stream_start")
            results = [provider.complete("writer", prompt, params, extra,
                                         stream_cb=(lambda t: _emit(events, "delta", text=t)) if events else None,
                                         meta=meta, token=token,
                                         on_retry_event=(lambda kind: _emit(events, kind)) if events else None)]
            _emit(events, "stream_end")
            streamed = True
        else:
            _emit(events, "progress",
                  msg=f"generating {count} candidates (max_parallel {p.cfg['max_parallel']})...")
            results = provider.many(one, count, token=token,
                                    on_event=(lambda ev: _emit_raw(events, ev)) if events else None)
            streamed = False
    except Cancelled:
        raise
    except (HttpErr, NoAnswerErr, httpx.HTTPError, FatalError) as e:
        raise OpError(f"generation failed: {e}", soft=True) from None
    _advance(p, baseline, "calib.json")   # our own calls may record calibration
    ids = []
    for text, finish, _ in results:
        if token:
            token.check()
        clean, ended, trimmed = clean_continuation(text, finish, rep["continuing"])
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


# ------------------------------------------------------ session/inspection

def session_info(root, scene_id=None):
    """Plain session defaults and prerequisite/warning report (no calls).

    `warnings` holds ignored project sampler keys and earlier-scene warnings;
    `sampler_warnings` holds preset sampler notes. The CLI prints warnings,
    then its preset line, then sampler warnings — keep that order when
    adapting; the GUI shows both lists combined."""
    info = {"swipes": 1, "passage_words": 220, "model": "", "preset_found": False,
            "creds_ok": False, "api_key_env": "", "warnings": [],
            "sampler_warnings": [], "scene_ok": False}
    p = _project_of(root)
    scenes = _scenes_or_error(p)
    rc = p.cfg["roles"]["writer"]
    info.update(swipes=max(1, int(rc.get("swipes", 1))),
                passage_words=int(rc.get("passage_words", 220)), model=rc["model"])
    key = str(p.cfg.get("api_key") or "").strip()
    env = str(p.cfg.get("api_key_env") or "")
    info["api_key_env"] = env
    if not key and env and os.environ.get(env, "").strip():
        key = "env"
    info["creds_ok"] = bool(key)
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
