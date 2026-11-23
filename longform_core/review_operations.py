"""Qt-independent continuity/review/revision/status/export operations (ADR-0007).

Extracted from commands.cmd_update_state/cmd_compress/cmd_critique/cmd_check/
cmd_revise and the computed facts behind cmd_status/cmd_export. No Qt imports
and no terminal helpers: plain-value inputs, typed progress events, an
injectable provider/cancellation token and stale-baseline guards before every
save. Prompt bytes, messages, files, reports, diffs and histories are
preserved exactly; the CLI adapters keep printing/paging/editor invocation in
commands.py. Preview sessions are in-memory records, never files: reopening
reads saved continuity/reports/history but cannot accept an old generation
without preparing against the current sources again.
"""

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .api import HttpErr, NoAnswerErr
from .cancel import Cancelled
from .checks import check_report
from .config import CRITIC_SYSTEM, EDITOR_SYSTEM, SUMMARIZER_SYSTEM
from .draft_operations import (OpError, _advance, _capture, _check_tree_writable,
                               _emit, _project_of, _provider, _stale_check,
                               _tree)
from .prompt import format_card, layered_summary
from .reader_model import _no_symlink_below
from .tree import Tree
from . import utils as _utils
from .utils import (extract_tagged, keep_lead, line_diff, parse_sections,
                    read_text, save_input, tag_instr, text_hash, warn,
                    word_diff, words, write_text)


def _scenes(p):
    try:
        return p.scenes()
    except Exception as e:  # noqa: BLE001 — sanitized below
        raise OpError(f"scenes.json could not be read ({type(e).__name__})") from None


def _sums(p):
    try:
        return p.summaries()
    except Exception as e:  # noqa: BLE001
        raise OpError(f"summaries.json could not be read ({type(e).__name__})") from None


def _find_idx(scenes, scene_id):
    return next((i for i, s in enumerate(scenes) if s.get("id") == scene_id), None)


# ================================================================= compress

@dataclass
class CompressPrep:
    from_id: str
    to_id: str
    lo: int
    hi: int
    user: str
    msgs: list
    overlaps: list          # whole existing arcs intersecting the range
    baseline: dict


def compress_overlaps(scenes, sums, lo, hi):
    """Inclusive overlap: shared endpoints count; arcs with endpoints absent
    from the current scene list are ignored, exactly like the CLI."""
    pos = {s["id"]: i for i, s in enumerate(scenes)}
    return [a for a in sums.get("arcs", [])
            if a["from"] in pos and a["to"] in pos
            and not (pos[a["to"]] < lo or pos[a["from"]] > hi)]


def compress_prepare(root, from_id, to_id, *, replace=False, token=None):
    """Validate the inclusive range and replacement set; no call, no write.

    Raises OpError(collision=True) naming the first overlapping arc when
    Replace consent is missing, like the CLI's die()."""
    p = _project_of(root)
    scenes = _scenes(p)
    lo = _find_idx(scenes, from_id)
    if lo is None:
        raise OpError(f"no scene with id {from_id}")
    hi = _find_idx(scenes, to_id)
    if hi is None:
        raise OpError(f"no scene with id {to_id}")
    if hi < lo:
        raise OpError("--to must not come before --from")
    sums = _sums(p)
    overlaps = compress_overlaps(scenes, sums, lo, hi)
    if overlaps and not replace:
        first = overlaps[0]
        raise OpError(f"overlaps existing arc {first['from']}-{first['to']} "
                      "(use --replace)", collision=True)
    rng = scenes[lo: hi + 1]
    missing = [s["id"] for s in rng if s["id"] not in sums["scenes"]]
    if missing:
        raise OpError("no summaries for: " + ", ".join(missing))
    body = "\n\n".join(
        f"### {s['id']}: {s.get('title', '')}\n{sums['scenes'][s['id']]['detailed']}"
        for s in rng)
    aw = p.cfg["summary"]["arc_words"]
    user = (f"# Scene summaries {rng[0]['id']}-{rng[-1]['id']}\n{body}\n\n"
            f"Condense these into one continuous summary of about {aw} words. "
            "Keep every fact later scenes may depend on: "
            "who knows what, promises and setups, injuries, objects, "
            "relationship changes, unresolved threads. " + tag_instr("summary"))
    msgs = [{"role": "system", "content": SUMMARIZER_SYSTEM},
            {"role": "user", "content": user}]
    baseline = _capture(p, ["project.json", "summaries.json"])
    if token:
        token.check()
    return CompressPrep(from_id=from_id, to_id=to_id, lo=lo, hi=hi, user=user,
                        msgs=msgs, overlaps=overlaps, baseline=baseline)


def compress_overlap_set(root, from_id, to_id):
    """Read-only whole-arc deletion set for the desktop Replace dialog."""
    p = _project_of(root)
    scenes = _scenes(p)
    lo = _find_idx(scenes, from_id)
    hi = _find_idx(scenes, to_id)
    if lo is None or hi is None or hi < lo:
        return []
    return compress_overlaps(scenes, _sums(p), lo, hi)


def compress_generate(root, prep, *, provider=None, provider_factory=None,
                      token=None, events=None):
    """One summarizer chat call for the arc summary; nothing written."""
    p = _project_of(root)
    if token:
        token.check()
    _emit(events, "progress",
          msg=f"compressing {prep.from_id}-{prep.to_id}...")
    provider = provider or _provider(p, provider_factory)
    try:
        raw, finish, _ = provider.chat("summarizer", prep.msgs, token=token,
                                       on_retry_event=(lambda why, delay:
                                                       _emit(events, "retry"))
                                                      if events else None)
    except Cancelled:
        raise
    except (HttpErr, NoAnswerErr) as e:
        raise OpError(f"summarizer failed: {e}", soft=True) from None
    _advance(p, prep.baseline, "calib.json")
    text, ok = extract_tagged(raw, "summary")
    return {"text": text, "ok": ok, "raw": raw,
            "from": prep.from_id, "to": prep.to_id}


def compress_save_edit_input(root, prep, text, *, token=None):
    """Keep the edited arc text as inputs/arc_<from>_<to>.md plus history;
    this never replaces an arc."""
    p = _project_of(root)
    if token:
        token.check()
    save_input(p.root, f"arc_{prep.from_id}_{prep.to_id}", text)
    return {"saved": f"inputs/arc_{prep.from_id}_{prep.to_id}.md"}


def compress_accept(root, prep, text, *, baseline=None, token=None,
                    events=None):
    """Explicit acceptance: remove whole overlapping arcs, append the new
    record; per-scene summaries and nonoverlapping arcs stay intact."""
    p = _project_of(root)
    baseline = dict(prep.baseline if baseline is None else baseline)
    if token:
        token.check()
    _stale_check(p, baseline)
    scenes = _scenes(p)
    sums = _sums(p)
    if prep.overlaps:
        pos = {s["id"]: i for i, s in enumerate(scenes)}
        arcs = [a for a in sums.get("arcs", [])
                if not (a["from"] in pos and a["to"] in pos
                        and not (pos[a["to"]] < prep.lo
                                 or pos[a["from"]] > prep.hi))]
    else:
        arcs = list(sums.get("arcs", []))
    arcs.append({"from": prep.from_id, "to": prep.to_id, "text": text,
                 "updated": _utils.now()})
    sums["arcs"] = arcs
    try:
        p.save_summaries(sums)
    except OSError as e:
        raise OpError(f"summaries.json could not be saved "
                      f"({type(e).__name__})", soft=True) from None
    _advance(p, baseline, "summaries.json")
    _emit(events, "accepted", arc=f"{prep.from_id}-{prep.to_id}")
    return {"message": f"saved arc {prep.from_id}-{prep.to_id}",
            "from": prep.from_id, "to": prep.to_id}


# ============================================================ update state

LATER_WARNING = ("state.md already includes later scenes ({later}); "
                 "updating state from this scene would treat that as 'before'. "
                 "Use --summary-only to refresh summaries only.")

_UPDATE_KEYS = ("project.json", "scenes.json", "summaries.json", "state.md",
                "bible.md", "limits.json", "calib.json")


@dataclass
class UpdateStatePrep:
    scene_id: str
    idx: int
    summary_only: bool
    names: list
    user: str
    msgs: list
    later: list
    warnings: list          # printed before the later-scene confirmation
    call_warnings: list     # printed after it, before the provider call
    scene_text: str
    state_text: str
    baseline: dict


def update_state_check(root, scene_id=None, summary_only=False):
    """Cheap read-only gating facts for the desktop (missing/empty/default
    scene, not-done warning, later-scene list); no provider call, no write."""
    p = _project_of(root)
    scenes = _scenes(p)
    out = {"scene_id": None, "idx": None, "warnings": [], "later": [],
           "error": None}
    if scene_id:
        idx = _find_idx(scenes, scene_id)
        if idx is None:
            out["error"] = f"no scene with id {scene_id}"
            return out
    else:
        idx = next((i for i, s in enumerate(scenes)
                    if s.get("status") == "done" and not s.get("state_updated")),
                   None)
        if idx is None:
            out["error"] = ("no done scene is waiting for a state update "
                            "(use --scene ID)")
            return out
    sc = scenes[idx]
    out["scene_id"], out["idx"] = sc["id"], idx
    if sc.get("status") != "done":
        out["warnings"].append(f"scene {sc['id']} is not marked done")
    out["later"] = [s["id"] for s in scenes[idx + 1:] if s.get("state_updated")]
    return out


def update_state_prepare(root, scene_id=None, summary_only=False,
                         *, token=None):
    """Resolve the scene, warnings and the exact summarizer messages; no call,
    no write. Raises OpError for unknown/empty scenes and no waiting scene."""
    p = _project_of(root)
    scenes = _scenes(p)
    if scene_id:
        idx = _find_idx(scenes, scene_id)
        if idx is None:
            raise OpError(f"no scene with id {scene_id}")
    else:
        idx = next((i for i, s in enumerate(scenes)
                    if s.get("status") == "done" and not s.get("state_updated")),
                   None)
        if idx is None:
            raise OpError("no done scene is waiting for a state update "
                          "(use --scene ID)")
    sc = scenes[idx]
    tree = _tree(p, sc["id"])
    if not tree.head:
        raise OpError(f"scene {sc['id']} has no text")
    warnings = []
    if sc.get("status") != "done":
        warnings.append(f"scene {sc['id']} is not marked done")
    later = [s["id"] for s in scenes[idx + 1:] if s.get("state_updated")]
    summary_only = bool(summary_only)
    scene_text = tree.text()
    try:
        bible = read_text(p.f("bible.md")).strip()
        state = read_text(p.f("state.md")).strip()
    except OSError as e:
        raise OpError(f"project source could not be read "
                      f"({type(e).__name__})") from None
    cfg = p.cfg["summary"]
    model = p.cfg["roles"]["summarizer"]["model"]
    names = ["DETAILED SUMMARY", "BRIEF SUMMARY"] + \
        ([] if summary_only else ["UPDATED STATE"])
    instr = (
        "Produce exactly these sections, each starting with its exact header line:\n"
        "=== DETAILED SUMMARY ===\n"
        f"(about {cfg['detailed_words']} words: what happens, in order, with concrete specifics: who did what, what was revealed, decisions made, how the scene ends)\n"
        "=== BRIEF SUMMARY ===\n"
        f"(about {cfg['brief_words']} words: key events and changes only)\n"
    )
    if not summary_only:
        instr += (
            "=== UPDATED STATE ===\n"
            "(the full continuity state after this scene, in the same markdown structure as the state before it. "
            "Keep every still-valid entry, update changed ones, add new ones; move finished threads to 'Resolved'. "
            "Cover each character's location, condition, knowledge, goals and relationships; open threads and setups; "
            "established facts and objects that must stay consistent.)\n"
        )
    instr += ("Put all the sections between <record> and </record> tags, with "
              "nothing else inside them. Anything outside the tags is discarded.")
    user = (f"# Story bible\n{bible}\n\n# Scene card\n{format_card(sc)}\n\n"
            + ("" if summary_only else
               f"# Continuity state BEFORE this scene\n{state}\n\n")
            + f"# Full text of the scene\n{scene_text}\n\n{instr}")
    msgs = [{"role": "system", "content": SUMMARIZER_SYSTEM},
            {"role": "user", "content": user}]
    call_warnings = []
    ceil, _, src = p.ceiling(model)
    need = p.est(model, SUMMARIZER_SYSTEM + user) + \
        int(p.cfg["roles"]["summarizer"]["max_tokens"])
    if need > ceil:
        call_warnings.append(f"request needs ~{need} tokens but ceiling is "
                             f"{ceil} ({src}); the call may fail")
    baseline = _capture(p, list(_UPDATE_KEYS) + [f"trees/{sc['id']}.json"])
    if token:
        token.check()
    return UpdateStatePrep(scene_id=sc["id"], idx=idx,
                           summary_only=summary_only, names=names, user=user,
                           msgs=msgs, later=later, warnings=warnings,
                           call_warnings=call_warnings, scene_text=scene_text,
                           state_text=state, baseline=baseline)


def provider_for(root, api_cls=None):
    """Construct the chat client exactly like the CLI (may die() on missing
    credentials). The CLI adapter passes the (possibly patched) Api class so
    its seam keeps working; ops default to the real Api."""
    from .api import Api as _Api
    return (api_cls or _Api)(_project_of(root))


def update_state_generate(root, prep, *, provider_factory=None, provider=None,
                          token=None, events=None):
    """One summarizer chat call with the prepared messages; nothing written."""
    p = _project_of(root)
    if token:
        token.check()
    _emit(events, "progress", msg=f"summarizing {prep.scene_id}...")
    provider = provider or _provider(p, provider_factory)
    try:
        raw, finish, _ = provider.chat("summarizer", prep.msgs, token=token,
                                       on_retry_event=(lambda why, delay:
                                                       _emit(events, "retry"))
                                                      if events else None)
    except Cancelled:
        raise
    except (HttpErr, NoAnswerErr) as e:
        raise OpError(f"summarizer failed: {e}", soft=True) from None
    _advance(p, prep.baseline, "calib.json")
    return {"raw": raw, "finish": finish, "scene": prep.scene_id}


def update_state_parse_response(raw, prep):
    """Parse a model response exactly like the CLI (extract_tagged, then the
    existing section parser)."""
    return update_state_parse_text(extract_tagged(raw or "", "record")[0], prep)


def update_state_parse_text(text, prep):
    """Parse raw/edited text with the existing section parser (no tagging)."""
    try:
        secs = parse_sections(text or "", prep.names)
    except Exception as e:  # noqa: BLE001 — malformed regex-free text is fine
        return {"secs": None, "error": str(e)}
    return {"secs": secs}


def edit_blob(prep, secs):
    """The exact section blob the CLI hands to its editor."""
    return "\n\n".join(f"=== {n} ===\n{secs[n]}" for n in prep.names)


def update_state_save_raw_input(root, scene_id, text, *, token=None):
    """Retain a raw correction in inputs/state_raw_<scene>.md plus its
    timestamped history version, even when it is still invalid."""
    p = _project_of(root)
    if token:
        token.check()
    save_input(p.root, f"state_raw_{scene_id}", text)
    return {"saved": f"inputs/state_raw_{scene_id}.md"}


def update_state_save_edit_input(root, scene_id, blob, *, token=None):
    """Retain section edits in inputs/state_edit_<scene>.md plus history;
    this never accepts the proposal."""
    p = _project_of(root)
    if token:
        token.check()
    save_input(p.root, f"state_edit_{scene_id}", blob)
    return {"saved": f"inputs/state_edit_{scene_id}.md"}


def update_state_accept(root, prep, secs, *, baseline=None, token=None,
                        events=None):
    """Explicit acceptance: the CLI's backup → state → summary → scenes save
    sequence behind one staleness/cancellation check. Summary-only does not
    modify state.md, its history or scene flags."""
    for n in prep.names:
        if not (secs or {}).get(n):
            raise OpError(f"section {n} is missing or empty; acceptance stays "
                          "disabled until the parser accepts every required "
                          "section", soft=True)
    p = _project_of(root)
    baseline = dict(prep.baseline if baseline is None else baseline)
    if token:
        token.check()
    _stale_check(p, baseline)
    summary_only = prep.summary_only
    if not summary_only:
        try:
            shutil.copy2(p.f("state.md"),
                         p.f("state_history",
                             f"before_{prep.scene_id}_{_utils.stamp()}.md"))
            write_text(p.f("state.md"), secs["UPDATED STATE"].strip() + "\n")
        except OSError as e:
            raise OpError(f"state could not be saved ({type(e).__name__}) "
                          "— earlier writes of this commit group may have "
                          "completed; check state_history/", soft=True) from None
        _advance(p, baseline, "state.md")
    scenes = _scenes(p)
    idx = _find_idx(scenes, prep.scene_id)
    if idx is None:
        raise OpError(f"no scene with id {prep.scene_id}", stale=True)
    sums = _sums(p)
    sums["scenes"][prep.scene_id] = {
        "detailed": secs["DETAILED SUMMARY"], "brief": secs["BRIEF SUMMARY"],
        "updated": _utils.now(), "text_hash": text_hash(prep.scene_text),
    }
    try:
        p.save_summaries(sums)
    except OSError as e:
        raise OpError(f"summaries.json could not be saved "
                      f"({type(e).__name__})", soft=True) from None
    _advance(p, baseline, "summaries.json")
    if not summary_only:
        scenes[idx]["state_updated"] = True
        try:
            p.save_scenes(scenes)
        except OSError as e:
            raise OpError(f"scenes.json could not be saved "
                          f"({type(e).__name__})", soft=True) from None
        _advance(p, baseline, "scenes.json")
    _emit(events, "accepted", scene=prep.scene_id, summary_only=summary_only)
    return {"scene": prep.scene_id, "summary_only": summary_only,
            "message": "saved summaries" + ("" if summary_only
                                            else " and state.md")}


def update_state_history(root, scene_id):
    """Read-only history: state backups for this scene plus saved raw/edit
    input versions (no restore/delete feature)."""
    p = _project_of(root)
    out = {"backups": [], "inputs": []}
    d = p.f("state_history")
    if d.is_dir():
        for f in sorted(d.glob(f"before_{scene_id}_*.md")):
            out["backups"].append({"name": f.name, "text": read_text(f)})
    for kind in (f"state_raw_{scene_id}", f"state_edit_{scene_id}"):
        cur = p.f("inputs", f"{kind}.md")
        if cur.exists():
            out["inputs"].append({"name": f"inputs/{kind}.md",
                                  "text": read_text(cur)})
        h = p.f("inputs", "history")
        if h.is_dir():
            for f in sorted(h.glob(f"{kind}_*.md")):
                out["inputs"].append({"name": f"inputs/history/{f.name}",
                                      "text": read_text(f)})
    return out
