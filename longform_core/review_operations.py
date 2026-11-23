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
                               _emit, _project_of, _provider, _save_tree,
                               _stale_check, _tree)
from .prompt import format_card, layered_summary
from .reader_model import _no_symlink_below
from .tree import Tree
from .utils import FatalError
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


# =========================================================== critique/check

@dataclass
class CritiquePrep:
    scene_id: str
    idx: int
    msgs: list
    warnings: list         # layered-summary notes (budget/missing)
    baseline: dict


def critique_extract(raw):
    """The CLI's extract_tagged for critique output."""
    text, ok = extract_tagged(raw or "", "critique")
    return {"text": text, "ok": ok}


def critique_prepare(root, scene_id, *, token=None):
    """Resolve the scene and build the exact critic request; no call, no
    write. Missing text is refused; layered-summary notes become warnings."""
    p = _project_of(root)
    scenes = _scenes(p)
    idx = _find_idx(scenes, scene_id)
    if idx is None:
        raise OpError(f"no scene with id {scene_id}")
    sc = scenes[idx]
    tree = _tree(p, scene_id)
    if not tree.head:
        raise OpError(f"scene {scene_id} has no text")
    model = p.cfg["roles"]["critic"]["model"]
    try:
        summary, notes = layered_summary(p, scenes, idx,
                                         int(p.cfg["budget_tokens"]["summary"]),
                                         model)
        banned = ", ".join(f'"{b}"' for b in p.cfg["banned_phrases"])
    except FatalError as e:
        raise OpError(str(e.msg), from_die=True) from None
    user = (
        f"# Story bible\n{read_text(p.f('bible.md')).strip()}\n\n"
        + (f"# Story before this scene\n{summary}\n\n" if summary else "")
        + f"# Current continuity state\n{read_text(p.f('state.md')).strip()}\n\n"
        f"# Scene card\n{format_card(sc)}\n\n# Scene text\n{tree.text()}\n\n"
        "Review the scene text. List every problem as a numbered item in this exact format:\n"
        'N. [category] "exact quote from the text" - what is wrong - concrete fix\n'
        "Categories: continuity (contradicts the summary, state or bible), cast (a character not listed as present "
        "appears, speaks or acts), pov-tense, style-rule, cliche, repetition, pacing (relative to the scene card's "
        "goal/conflict/outcome), dialogue, logic.\n"
        f"Phrases the author has banned: {banned}.\n"
        "After the list, one line: 'Scene card fulfilled: yes/partly/no - reason'. "
        + tag_instr("critique")
    )
    msgs = [{"role": "system", "content": CRITIC_SYSTEM},
            {"role": "user", "content": user}]
    baseline = _capture(p, ["project.json", "scenes.json", "summaries.json",
                            "bible.md", "state.md", "limits.json",
                            "calib.json", f"trees/{scene_id}.json",
                            f"critiques/{scene_id}.md"])
    if token:
        token.check()
    return CritiquePrep(scene_id=scene_id, idx=idx, msgs=msgs,
                        warnings=list(notes), baseline=baseline)


def critique_generate(root, prep, *, provider=None, provider_factory=None,
                      token=None, events=None):
    """One critic chat call with the prepared messages; nothing written."""
    p = _project_of(root)
    if token:
        token.check()
    _emit(events, "progress", msg=f"critiquing {prep.scene_id}...")
    provider = provider or _provider(p, provider_factory)
    try:
        raw, finish, _ = provider.chat("critic", prep.msgs, token=token,
                                       on_retry_event=(lambda why, delay:
                                                       _emit(events, "retry"))
                                                      if events else None)
    except Cancelled:
        raise
    except (HttpErr, NoAnswerErr) as e:
        raise OpError(f"critic failed: {e}", soft=True) from None
    _advance(p, prep.baseline, "calib.json")
    return {"raw": raw, "finish": finish, "scene": prep.scene_id}


def critique_save(root, prep, text, *, baseline=None, token=None, events=None):
    """Explicit save: the CLI heading/body bytes; an existing report is
    copied to <scene>_prev_<stamp>.md first."""
    p = _project_of(root)
    baseline = dict(prep.baseline if baseline is None else baseline)
    if token:
        token.check()
    if not _no_symlink_below(p.root, "critiques", f"{prep.scene_id}.md"):
        raise OpError(f"critiques/{prep.scene_id}.md is a symlink; refusing "
                      "to write")
    _stale_check(p, baseline)
    out = p.f("critiques", f"{prep.scene_id}.md")
    backup = None
    try:
        if out.exists():
            backup = f"{prep.scene_id}_prev_{_utils.stamp()}.md"
            shutil.copy2(out, p.f("critiques", backup))
        write_text(out, f"# Critique {prep.scene_id} ({_utils.now()})\n\n"
                        f"{text}\n")
    except OSError as e:
        raise OpError(f"critiques/{prep.scene_id}.md could not be saved "
                      f"({type(e).__name__})", soft=True) from None
    _advance(p, baseline, f"critiques/{prep.scene_id}.md")
    _emit(events, "saved", scene=prep.scene_id)
    return {"scene": prep.scene_id, "ok": True, "backup": backup,
            "path": str(out),
            "message": f"wrote {out} (edit it to drop points you disagree "
                       "with before running revise)"}


def report_baseline(root, sub, name):
    """Captured bytes of a saved report for edit/save staleness checks."""
    p = _project_of(root)
    return _capture(p, [f"{sub}/{name}.md"])


def report_save_edit(root, sub, name, text, *, baseline=None, token=None,
                     events=None):
    """Save a built-in review-note edit verbatim at the existing report path;
    critique edits use the same prev-backup convention, check edits none."""
    p = _project_of(root)
    if sub not in ("critiques", "checks"):
        raise OpError(f"unknown report directory {sub}", soft=True)
    baseline = dict(report_baseline(root, sub, name)
                    if baseline is None else baseline)
    if token:
        token.check()
    if not _no_symlink_below(p.root, sub, f"{name}.md"):
        raise OpError(f"{sub}/{name}.md is a symlink; refusing to write")
    _stale_check(p, baseline)
    out = p.f(sub, f"{name}.md")
    backup = None
    try:
        if sub == "critiques" and out.exists():
            backup = f"{name}_prev_{_utils.stamp()}.md"
            shutil.copy2(out, p.f(sub, backup))
        write_text(out, text)
    except OSError as e:
        raise OpError(f"{sub}/{name}.md could not be saved "
                      f"({type(e).__name__})", soft=True) from None
    _advance(p, baseline, f"{sub}/{name}.md")
    _emit(events, "saved", report=f"{sub}/{name}.md")
    return {"sub": sub, "name": name, "backup": backup, "path": str(out)}


def check_report_for(root, scene_id=None, *, token=None):
    """Deterministic check over the selected scene or all scenes' active
    paths (empty scenes skipped); no provider instance or credential is
    involved."""
    p = _project_of(root)
    scenes = _scenes(p)
    if scene_id:
        idx = _find_idx(scenes, scene_id)
        if idx is None:
            raise OpError(f"no scene with id {scene_id}")
        targets = [scenes[idx]]
    else:
        targets = scenes
    banned = [b for b in p.cfg["banned_phrases"] if b.strip()]
    ng = p.cfg["ngram"]
    n, min_count, top = int(ng["n"]), int(ng["min_count"]), int(ng["top"])
    scene_texts = []
    keys = ["project.json", "scenes.json"]
    for s in targets:
        tree = _tree(p, s["id"])
        keys.append(f"trees/{s['id']}.json")
        if not tree.head:
            continue
        scene_texts.append((s["id"],
                            [(nid, tree.node(nid)["text"])
                             for nid in tree.chain()],
                            tree.text()))
    baseline = _capture(p, keys + [f"checks/{scene_id or 'all'}.md"])
    if token:
        token.check()
    title = (f"# Check {'scene ' + scene_id if scene_id else 'all scenes'} "
             f"({_utils.now()})")
    report = check_report(scene_texts, banned, n, min_count, top, title)
    name = scene_id or "all"
    return {"name": name, "report": report, "baseline": baseline,
            "path": str(p.f("checks", f"{name}.md"))}


def check_save(root, name, report, *, baseline=None, token=None, events=None):
    """Explicit save of the scoped report; overwrites the existing path with
    no new backup scheme."""
    p = _project_of(root)
    baseline = dict(report_baseline(root, "checks", name)
                    if baseline is None else baseline)
    if token:
        token.check()
    if not _no_symlink_below(p.root, "checks", f"{name}.md"):
        raise OpError(f"checks/{name}.md is a symlink; refusing to write")
    _stale_check(p, baseline)
    out = p.f("checks", f"{name}.md")
    try:
        write_text(out, report)
    except OSError as e:
        raise OpError(f"checks/{name}.md could not be saved "
                      f"({type(e).__name__})", soft=True) from None
    _advance(p, baseline, f"checks/{name}.md")
    _emit(events, "saved", report=f"checks/{name}.md")
    return {"name": name, "path": str(out), "message": f"wrote {out}"}


# ================================================================ revise

@dataclass
class ReviseSession:
    scene_id: str
    chain: list
    k: int = 0
    changed: int = 0
    notes_text: str = ""
    baseline: dict = field(default_factory=dict)
    finished: bool = False


def revise_prepare(root, scene_id, *, token=None):
    """Begin a revision session: captured chain and saved notes (critique
    then scene check; checks/all.md is never substituted)."""
    p = _project_of(root)
    scenes = _scenes(p)
    _find_idx(scenes, scene_id) or _require_scene(scenes, scene_id)
    tree = _tree(p, scene_id)
    if not tree.head:
        raise OpError(f"scene {scene_id} has no text")
    notes = []
    for path in (p.f("critiques", f"{scene_id}.md"),
                 p.f("checks", f"{scene_id}.md")):
        if path.exists():
            notes.append(read_text(path).strip())
    if not notes:
        raise OpError(f"no notes for {scene_id}: run critique {p.root} "
                      f"--scene {scene_id} and/or check {p.root} --scene "
                      f"{scene_id} first")
    baseline = _capture(p, ["project.json", "scenes.json", "summaries.json",
                            "bible.md", "state.md", "limits.json",
                            "calib.json", f"trees/{scene_id}.json",
                            f"critiques/{scene_id}.md",
                            f"checks/{scene_id}.md"])
    if token:
        token.check()
    return ReviseSession(scene_id=scene_id, chain=tree.chain(),
                         notes_text="\n\n".join(notes), baseline=baseline)


def _require_scene(scenes, scene_id):
    if _find_idx(scenes, scene_id) is None:
        raise OpError(f"no scene with id {scene_id}")


def revise_passage(root, session, k):
    """The exact captured request for passage k (re-read from the saved tree
    so earlier accepted edits are visible, as in the CLI)."""
    p = _project_of(root)
    scenes = _scenes(p)
    idx = _find_idx(scenes, session.scene_id)
    if idx is None:
        raise OpError(f"no scene with id {session.scene_id}", stale=True)
    sc = scenes[idx]
    tree = _tree(p, session.scene_id)
    if k < 0 or k >= len(session.chain):
        raise OpError("no such passage", soft=True)
    nid = session.chain[k]
    if nid not in tree.d["nodes"]:
        raise OpError(f"node {nid} is no longer present; restart the "
                      "revision session", stale=True)
    n = tree.node(nid)
    prev_tail = tree.text(session.chain[k - 1])[-900:] if k > 0 else ""
    cast = ", ".join(sc.get("characters") or [])
    user = (
        f"# Story bible (style rules apply)\n"
        f"{read_text(p.f('bible.md')).strip()}\n\n"
        + (f"# Characters present in this scene\n{cast}\n\n" if cast else "")
        + f"# Editor's notes for this scene\n{session.notes_text}\n\n"
        + (f"# Text just before the passage (context only, do not output "
           f"it)\n...{prev_tail}\n\n" if prev_tail else "")
        + f"# Passage to revise\n{n['text'].strip()}\n\n"
        "Fix only the listed problems that occur in this passage. If none "
        "occur in it, answer NO CHANGES. Otherwise answer with the full "
        "revised passage. " + tag_instr("passage")
    )
    msgs = [{"role": "system", "content": EDITOR_SYSTEM},
            {"role": "user", "content": user}]
    cap = max(int(p.cfg["roles"]["editor"]["max_tokens"]),
              int(words(n["text"]) * 2))
    return {"nid": nid, "k": k, "total": len(session.chain),
            "original": n["text"].strip(), "msgs": msgs, "cap": cap,
            "sep_empty": n.get("sep") == ""}


def revise_generate(root, session, k, *, provider=None, provider_factory=None,
                    token=None, events=None):
    """One editor chat call for passage k; nothing written."""
    p = _project_of(root)
    psg = revise_passage(root, session, k)
    if token:
        token.check()
    _emit(events, "progress",
          msg=f"revising {psg['nid']} ({psg['k'] + 1}/{psg['total']})...")
    provider = provider or _provider(p, provider_factory)
    try:
        raw, finish, _ = provider.chat("editor", psg["msgs"],
                                       max_tokens=psg["cap"], token=token,
                                       on_retry_event=(lambda why, delay:
                                                       _emit(events, "retry"))
                                                      if events else None)
    except Cancelled:
        raise
    except (HttpErr, NoAnswerErr) as e:
        raise OpError(f"editor failed: {e}", soft=True) from None
    _advance(p, session.baseline, "calib.json")
    text, ok = extract_tagged(raw, "passage")
    return dict(psg, text=text, ok=ok, finish=finish)


def revise_save_edit_input(root, session, nid, text, *, token=None):
    """Keep the edited proposal in inputs/revise_<scene>_<node>.md plus
    history; the node still needs Accept."""
    p = _project_of(root)
    if token:
        token.check()
    save_input(p.root, f"revise_{session.scene_id}_{nid}", text)
    return {"saved": f"inputs/revise_{session.scene_id}_{nid}.md"}


def revise_accept(root, session, k, psg, text, *, baseline=None, token=None,
                  events=None):
    """Accept one passage: history + in-place text change on the existing
    node (shared ancestors on other branches change too, as in the CLI);
    head/branches/separators/metadata are untouched."""
    if not (text or "").strip():
        raise OpError("empty text cannot replace prose", soft=True)
    p = _project_of(root)
    baseline = dict(session.baseline if baseline is None else baseline)
    if token:
        token.check()
    _stale_check(p, baseline)
    tree = _tree(p, session.scene_id)
    nid = psg["nid"]
    if nid not in tree.d["nodes"]:
        raise OpError(f"node {nid} is no longer present; restart the "
                      "revision session", stale=True)
    n = tree.node(nid)
    new = text
    if psg.get("sep_empty"):
        new = keep_lead(n["text"], new)
    n["history"].append({"time": _utils.now(), "text": n["text"],
                         "by": "revise"})
    n["text"] = new
    _save_tree(tree, p, session.scene_id, baseline)
    session.baseline = baseline
    session.changed += 1
    _emit(events, "accepted", nid=nid, changed=session.changed)
    return {"nid": nid, "changed": session.changed}


def revise_finish(root, session):
    """Normal completion facts: revised count and the CLI's
    normal-completion-only stale-summary warning."""
    p = _project_of(root)
    rec = _sums(p)["scenes"].get(session.scene_id)
    stale = bool(session.changed) and rec is not None
    return {"changed": session.changed,
            "message": f"revised {session.changed} passages",
            "stale": stale,
            "stale_message": (f"summary for {session.scene_id} is now stale "
                              f"(run: update-state {p.root} --scene "
                              f"{session.scene_id} --summary-only)")
            if stale else ""}


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
