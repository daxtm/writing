"""Qt-independent planning operations shared by the CLI and the GUI (ADR-0007).

Extracted from commands.cmd_init/limits/bible/outline/scenes incrementally:
plain captured inputs, opaque expected baselines, optional provider
factory/token/event sink; sanitized plain view/result/error records. The CLI
keeps questions, printing, paging and $EDITOR as an adapter with unchanged
prompts, files and transcripts; GUI calls never reach ask/page/edit_text or
subprocess commands. Operations separate prepare/generate, preview and
explicit commit: workers never wait for an author decision.
"""

import json
import os
import re
from pathlib import Path

from .api import Api, HttpErr
from .cancel import Cancelled
from .config import BIBLE_TEMPLATE, DEFAULT_CONFIG, STATE_TEMPLATE
from .draft_operations import (_advance, _capture, _emit, _project_of,
                               _provider, _read_bytes, _scenes_or_error,
                               _stale_check, OpError)
from .reader_model import _no_symlink_below
from .project import Project
from .utils import (FatalError, deep_merge, now, read_text, save_input, stamp,
                    write_text)

# ------------------------------------------------------- initialization


INIT_FILES = {
    "project.json": json.dumps(DEFAULT_CONFIG, indent=2) + "\n",
    "bible.md": BIBLE_TEMPLATE,
    "state.md": STATE_TEMPLATE,
    "scenes.json": "[]\n",
    "summaries.json": json.dumps({"scenes": {}, "arcs": []}, indent=2) + "\n",
}
INIT_DIRS = ("trees", "outlines", "critiques", "checks", "state_history",
             "lorebooks", "bible_history")


def canonical_root(root):
    """One canonical absolute project path; never follows a symlinked root."""
    root = Path(root).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    return Path(os.path.normpath(str(root)))


def _write_bytes_safe(path, data):
    """Atomic byte write refusing an existing non-file or symlink target."""
    if path.is_symlink():
        raise OpError(f"{path.name} is a symlink; refusing to write")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def init_project(root, *, preset_src=None, token=None, events=None):
    """Create-missing-only initialization with cmd_init's exact payloads.

    Existing files are never replaced, even malformed; a name collision with a
    directory or symlink is an error (with what was already created reported),
    not permission to reset. A preset source imports through the existing
    master-export validation without overwriting an existing destination.
    """
    root = canonical_root(root)
    if token:
        token.check()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise OpError(f"the project directory could not be created "
                      f"({type(e).__name__})") from None
    made, dirs_made, problems = [], [], []
    for name, content in INIT_FILES.items():
        path = root / name
        try:
            if path.is_symlink():
                raise OpError(f"{name} is a symlink; not overwritten")
            if path.exists() and not path.is_file():
                raise OpError(f"{name} exists and is not a regular file; "
                              "not overwritten")
        except OSError as e:
            raise OpError(f"{name} could not be inspected "
                          f"({type(e).__name__})") from None
        if not path.exists():
            write_text(path, content)
            made.append(name)
    for d in INIT_DIRS:
        dp = root / d
        if dp.is_symlink():
            raise OpError(f"{d}/ is a symlink; not replaced"
                          + _partial_note(made, dirs_made))
        if dp.exists():
            if not dp.is_dir():
                raise OpError(f"{d} exists and is not a directory; not replaced"
                              + _partial_note(made, dirs_made))
            continue
        try:
            dp.mkdir()
        except OSError as e:
            raise OpError(f"{d}/ could not be created ({type(e).__name__})"
                          + _partial_note(made, dirs_made)) from None
        dirs_made.append(d)
    preset = None
    if preset_src:
        preset = import_preset(root, preset_src, token=token)
    _emit(events, "initialized", created=len(made))
    return {"root": str(root), "created": made, "dirs": dirs_made,
            "preset": preset, "warnings": problems}


def _partial_note(made, dirs_made):
    if made or dirs_made:
        return (f" (created before the error: "
                f"{', '.join(made + dirs_made)}; initialization is not a "
                "transaction)")
    return ""


REQUIRED_PRESET_KEYS = ("instruct", "context", "sysprompt", "preset")


def import_preset(root, src, *, token=None, events=None):
    """Copy an explicitly picked SillyTavern master export to writer_preset.json.

    Unchanged source bytes; never overwrites an existing destination (no
    Replace button); an invalid or unreadable source changes nothing.
    """
    root = canonical_root(root)
    dst = root / "writer_preset.json"
    if dst.is_symlink() or (dst.exists() and not dst.is_file()):
        raise OpError("writer_preset.json exists and is not a regular file; "
                      "not overwritten", collision=True)
    if dst.exists():
        raise OpError("writer_preset.json already exists; not overwritten "
                      "(configure an existing preset path in Settings if "
                      "appropriate)", collision=True)
    src = Path(src).expanduser()
    try:
        data = src.read_bytes()
    except OSError as e:
        raise OpError("the selected preset could not be read "
                      f"({type(e).__name__})") from None
    try:
        d = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise OpError(f"the selected preset is not valid JSON: {e}") from None
    if not isinstance(d, dict):
        raise OpError("the selected preset is not a SillyTavern master export "
                      "(not a JSON object)")
    for k in REQUIRED_PRESET_KEYS:
        if k not in d:
            raise OpError("the selected preset is not a SillyTavern master "
                          f"export (missing '{k}')")
    if token:
        token.check()
    try:
        _write_bytes_safe(dst, data)
    except OSError as e:
        raise OpError(f"writer_preset.json could not be written "
                      f"({type(e).__name__})") from None
    _emit(events, "preset_imported", name="writer_preset.json")
    return {"imported": "writer_preset.json", "bytes": len(data),
            "replaced": False}


# ----------------------------------------------------------------- bible

def _dry_lore_names(p, scenes):
    """Character lorebook names without any registry write (safe read-only
    discovery matching what Lore.sync would classify)."""
    names = []
    d = p.f("lorebooks")
    if not d.is_dir() or d.is_symlink():
        return names
    try:
        files = sorted(x for x in d.iterdir()
                       if x.suffix.lower() in (".json", ".png"))
    except OSError:
        return names
    reg = {"books": {}}
    if p.f("lorebooks.json").is_file() and not p.f("lorebooks.json").is_symlink():
        try:
            raw = json.loads(p.f("lorebooks.json").read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("books"), dict):
                reg = raw
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            reg = {"books": {}}
    known = [c for s in scenes for c in (s.get("characters") or [])]
    from .lore import parse_book_data
    for path in files:
        meta = reg["books"].get(path.name)
        if isinstance(meta, dict):
            if meta.get("kind") == "character":
                names.append(meta.get("character") or path.stem)
            continue
        try:
            if path.suffix.lower() == ".png":
                from .lore import read_card_png
                data = read_card_png(path)
                card_name, _entries = parse_book_data(data, path.stem) \
                    if data is not None else (None, [])
            else:
                d2 = json.loads(path.read_text(encoding="utf-8"))
                card_name, _entries = parse_book_data(d2, path.stem)
        except Exception:  # noqa: BLE001 — an unreadable book is skipped
            continue
        if card_name:
            names.append(card_name)
            continue
        stem = re.sub(r"[^a-z0-9]+", " ", path.stem.lower()).split()
        for name in known:
            toks = name.lower().split()
            if stem and toks and stem[0] == toks[0]:
                names.append(name)
                break
    return names


def _split_safe(p):
    """(pre, secs) of bible.md or the template; an unparsable bible is an
    error outcome, never a reset."""
    path = p.f("bible.md")
    text = read_text(path) or BIBLE_TEMPLATE
    from .commands import split_bible
    pre, secs = split_bible(text)
    return path, text, pre, secs


def bible_overview(root):
    """Read-only section list, current bodies and the writer-token budget."""
    p = _project_of(root)
    scenes = _scenes_or_error(p)
    path, text, pre, secs = _split_safe(p)
    out = {"has_sections": bool(secs), "sections": [], "error": None,
           "chars": _dry_lore_names(p, scenes), "bible_path": "bible.md"}
    if not secs:
        out["error"] = "bible.md has no '## ' sections to work through"
        return out
    from .commands import is_placeholder
    for heading, body in secs:
        out["sections"].append({
            "heading": heading,
            "body": body,
            "placeholder": is_placeholder(body),
            "current": "(empty / template placeholder)" if is_placeholder(body)
            else body.strip(),
        })
    model = p.cfg["roles"]["writer"]["model"]
    out["tokens"] = p.est(model, text)
    out["budget"] = int(p.cfg["budget_tokens"]["bible"])
    out["over_budget"] = out["tokens"] > out["budget"]
    return out


def bible_form_state(root, heading):
    """The fixed form for one section (saved answers if present) plus the
    current section text; read-only, no session side effects."""
    p = _project_of(root)
    _scenes_or_error(p)
    path, _text, _pre, secs = _split_safe(p)
    from .commands import bible_form, is_placeholder
    if not secs:
        raise OpError("bible.md has no '## ' sections to work through")
    if heading not in [h for h, _b in secs]:
        raise OpError(f"no such bible section: {heading}")
    body = dict(secs)[heading]
    akind = f"bible_answers_{_slug(heading)}"
    saved = p.f("inputs", f"{akind}.md")
    if saved.is_symlink():
        raise OpError(f"inputs/{akind}.md is a symlink; refusing to read it "
                      "as answers")
    if saved.exists():
        form = read_text(saved)
        loaded = True
    else:
        form = bible_form(heading, _dry_lore_names(p, _scenes_or_error(p)))
        loaded = False
    return {"heading": heading, "form": form, "saved_form": loaded,
            "current": ("(empty / template placeholder)"
                        if is_placeholder(body) else body.strip()),
            "form_path": f"inputs/{akind}.md"}


def _slug(heading):
    from .utils import slug
    return slug(heading)


def begin_bible_session(root, *, token=None, events=None):
    """Back up the existing bible once, as cmd_bible does when answering
    starts; viewing alone never copies anything."""
    p = _project_of(root)
    path = p.f("bible.md")
    backup = None
    if path.exists():
        if not _no_symlink_below(p.root, "bible_history"):
            raise OpError("bible_history/ is a symlink; refusing to back up")
        if path.is_symlink():
            raise OpError("bible.md is a symlink; refusing to back it up")
        p.f("bible_history").mkdir(exist_ok=True)
        base = f"bible_{stamp()}"
        dest = p.f("bible_history", base + ".md")
        n = 1
        while dest.exists():
            n += 1
            dest = p.f("bible_history", f"{base}_{n}.md")
        import shutil
        try:
            shutil.copy2(path, dest)
        except OSError as e:
            raise OpError(f"the bible backup could not be written "
                          f"({type(e).__name__})") from None
        backup = f"bible_history/{dest.name}"
    _emit(events, "bible_session_started", backup=backup)
    return {"backup": backup}


def _bible_write(p, heading, section, baseline, *, token=None):
    """Shared acceptance boundary: stale/unsafe checks, then a single-section
    replacement through the captured preamble/order."""
    if not isinstance(baseline, dict) or "bible.md" not in baseline or \
            "secs" not in baseline or "pre" not in baseline:
        raise OpError("no captured bible baseline; reload the bible before "
                      "saving")
    if not _no_symlink_below(p.root, "bible.md"):
        raise OpError("bible.md is a symlink; refusing to write")
    secs = baseline["secs"]
    if heading not in [h for h, _b in secs]:
        raise OpError(f"no such bible section: {heading}")
    if token:
        token.check()
    _stale_check(p, {"bible.md": baseline["bible.md"]})
    new_secs = [(h, section if h == heading else b) for h, b in secs]
    from .commands import join_bible
    write_text(p.f("bible.md"), join_bible(baseline["pre"], new_secs))
    return new_secs


def _capture_bible_baseline(p):
    path, _text, pre, secs = _split_safe(p)
    return {"bible.md": _read_bytes(path, "bible.md"), "pre": pre,
            "secs": [(h, b) for h, b in secs]}


def bible_baseline(root):
    """Opaque bible edit baseline: exact bible.md bytes plus the captured
    preamble/ordered sections carried through preview to Accept."""
    p = _project_of(root)
    return _capture_bible_baseline(p)


def save_bible_answers(root, heading, form, *, token=None, events=None):
    """Persist the exact form and input history, then preview the composed
    section without changing bible.md."""
    p = _project_of(root)
    _scenes_or_error(p)
    akind = f"bible_answers_{_slug(heading)}"
    if not _no_symlink_below(p.root, "inputs", f"{akind}.md"):
        raise OpError(f"inputs/{akind}.md is a symlink; refusing to save")
    if token:
        token.check()
    from .commands import compose_section
    from .utils import save_input
    save_input(p.root, akind, form)
    section = compose_section(heading, form)
    _emit(events, "bible_answers_saved", heading=heading)
    return {"heading": heading, "preview": section,
            "words": _words(section), "form_path": f"inputs/{akind}.md"}


def accept_bible_section(root, heading, section, baseline, *, token=None,
                         events=None):
    """Explicit acceptance: replace only the chosen section of the captured
    bible (preamble, order and other sections preserved under existing join
    normalization). The unaccepted preview never touches bible.md."""
    p = _project_of(root)
    new_secs = _bible_write(p, heading, section, baseline, token=token)
    _emit(events, "bible_section_accepted", heading=heading)
    return {"heading": heading, "words": _words(section),
            "backup": "bible_history (captured at session begin)"}


def edit_bible_section(root, heading, new_body, baseline, *, token=None,
                       events=None):
    """Direct freeform section-text edit through the same backed-up
    boundary; custom headings and preamble are never relabeled or dropped."""
    p = _project_of(root)
    new_secs = _bible_write(p, heading, (new_body or "").strip("\n"),
                            baseline, token=token)
    _emit(events, "bible_section_edited", heading=heading)
    return {"heading": heading, "words": _words(new_body or "")}


def _words(text):
    from .utils import words
    return words(text or "")


def bible_history(root):
    """Read-only history listing: bible snapshots and saved answer inputs."""
    p = _project_of(root)
    out = {"bibles": [], "answers": [], "errors": []}
    for sub, key, ext in (("bible_history", "bibles", ".md"),
                          (("inputs", "history"), "answers", ".md")):
        d = p.f(*((sub,) if isinstance(sub, str) else sub))
        if not d.is_dir() or d.is_symlink():
            continue
        try:
            names = sorted(x.name for x in d.iterdir()
                           if x.name.endswith(ext) and x.is_file())
        except OSError as e:
            out["errors"].append(f"{key} could not be listed")
            continue
        for name in names:
            if not _no_symlink_below(p.root,
                                     *((sub,) if isinstance(sub, str) else sub),
                                     name):
                out["errors"].append(f"{name} is a symlink and was skipped")
                continue
            out[key].append({"name": name,
                             "text": read_text(d / name)})
    return out


# ---------------------------------------------------------------- outline

OUTLINE_NOTES_FORM = ("# Notes for the outline: anything you want the planner "
                      "to follow (pacing, key events, the ending, tone).\n"
                      "# Lines starting with # are ignored. Leave empty for "
                      "no notes.\n\n")


def outline_overview(root):
    """Read-only outline pane state: saved notes, saved outline, candidates."""
    p = _project_of(root)
    notes_file = p.f("inputs", "outline_notes.md")
    if notes_file.is_symlink():
        raise OpError("inputs/outline_notes.md is a symlink; refusing to read")
    raw_notes = read_text(notes_file) if notes_file.exists() else \
        OUTLINE_NOTES_FORM
    candidates = []
    d = p.f("outlines")
    if d.is_dir() and not d.is_symlink():
        try:
            candidates = sorted(x.name for x in d.glob("candidate_*.md"))
        except OSError:
            candidates = []
    outline = None
    op = p.f("outline.md")
    if op.exists():
        if op.is_symlink():
            outline = None
        else:
            outline = read_text(op)
    bible = read_text(p.f("bible.md")).strip()
    return {"notes_form": raw_notes, "notes": _filter_notes(raw_notes),
            "outline": outline, "candidates": candidates,
            "bible_present": bool(bible), "target_words":
                int(p.cfg["target_words"])}


def _filter_notes(raw_notes):
    return "\n".join(ln for ln in (raw_notes or "").splitlines()
                     if not ln.lstrip().startswith("#")).strip()


def save_outline_notes(root, form, *, token=None, events=None):
    """Save the notes form exactly (CLI --notes / edit-notes-and-reroll)."""
    p = _project_of(root)
    if not _no_symlink_below(p.root, "inputs", "outline_notes.md"):
        raise OpError("inputs/outline_notes.md is a symlink; refusing to save")
    if token:
        token.check()
    from .utils import save_input
    save_input(p.root, "outline_notes", form)
    _emit(events, "outline_notes_saved")
    return {"notes": _filter_notes(form), "form_path":
            "inputs/outline_notes.md"}


def outline_messages(bible, notes, tw):
    """The exact cmd_outline planner messages (pure)."""
    from .config import PLANNER_SYSTEM
    from .utils import tag_instr
    lo, hi = max(1, tw // 1500), max(2, tw // 800)
    user = (
        f"# Story bible\n{bible}\n\n"
        + (f"# Author's notes for this outline (follow them)\n{notes}\n\n"
           if notes else "")
        + f"Design a complete outline for a story of about {tw} words.\n"
        "Format (markdown):\n"
        "- Parts/acts, then chapters, then numbered beats per chapter.\n"
        "- Every beat is a concrete event: who does what, what changes.\n"
        "- Give each chapter an approximate word count; the counts must sum "
        "to roughly the target.\n"
        f"- A {tw}-word story has room for roughly {lo}-{hi} scenes; pace "
        "accordingly.\n"
        "- End with a section 'Threads & payoffs' listing each setup and the "
        "beat where it pays off.\n"
        + tag_instr("outline")
    )
    return [{"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": user}]


def outline_baseline(root, candidates=()):
    """Baselines carried from generation to a later choose/save."""
    p = _project_of(root)
    keys = ["bible.md", "outline.md", "inputs/outline_notes.md",
            "project.json"]
    for name in candidates:
        keys.append(f"outlines/{name}")
    return _capture(p, keys)


def generate_outlines(root, notes_form, n, *, provider_factory=None, token=None,
                      events=None):
    """N competing planner candidates via the shared chat_many: exact CLI
    messages, tag extraction, candidate naming and the optional leading notes
    comment. Rerolls append; nothing replaces outline.md."""
    p = _project_of(root)
    bible = read_text(p.f("bible.md")).strip()
    if not bible:
        raise OpError("bible.md is empty or missing; the outline planner "
                      "needs the bible (answer and accept a section first)",
                      soft=True)
    tw = int(p.cfg["target_words"])
    n = max(1, int(n))
    notes = _filter_notes(notes_form)
    if token:
        token.check()
    if not _no_symlink_below(p.root, "inputs", "outline_notes.md"):
        raise OpError("inputs/outline_notes.md is a symlink; refusing to save")
    baseline = _capture(p, ["bible.md", "outline.md", "project.json",
                            "inputs/outline_notes.md"])
    from .utils import save_input
    save_input(p.root, "outline_notes", notes_form)
    _advance(p, baseline, "inputs/outline_notes.md")
    _emit(events, "notes_saved")
    msgs = outline_messages(bible, notes, tw)
    provider = _provider(p, provider_factory)
    _emit(events, "progress", msg=f"generating {n} outline candidate(s) "
          f"(max_parallel {p.cfg['max_parallel']})")
    from .utils import extract_tagged
    try:
        res = provider.chat_many("planner", msgs, n, token=token,
                                 on_event=None if events is None else (
                                     lambda ev: _emit(events, ev.get("type"),
                                                      **{k: v for k, v in
                                                         ev.items()
                                                         if k != "type"})))
    except Cancelled:
        raise
    except Exception as e:  # noqa: BLE001 — sanitized outcome
        raise OpError(f"outline generation failed: {e}", soft=True) from None
    ts = stamp()
    existing = 0
    d = p.f("outlines")
    if d.is_dir():
        existing = len(list(d.glob("candidate_*.md")))
    saved, warnings = [], []
    for text, _finish, _u in res:
        if token:
            token.check()
        body, ok = extract_tagged(text, "outline")
        if not ok:
            warnings.append("a candidate had no <outline> tags; check it for "
                            "stray text")
        name = f"candidate_{ts}_{existing + len(saved) + 1}.md"
        if not _no_symlink_below(p.root, "outlines", name):
            raise OpError(f"outlines/{name} is a symlink; refusing to write")
        write_text(p.f("outlines", name),
                   (f"<!-- notes: {notes} -->\n" if notes else "") + body + "\n")
        saved.append(name)
    if not saved:
        warnings.append("no candidates came back")
    if len(res) < n:
        warnings.append(f"only {len(res)} of {n} requested outline "
                        "candidates came back")
    _emit(events, "outlines_saved", count=len(saved))
    return {"candidates": saved, "warnings": warnings, "notes": notes,
            "shortfall": max(0, n - len(res)), "bible_present": True,
            "baseline": baseline}


def read_outline_candidate(root, name):
    """Full candidate text for viewing (safe read)."""
    p = _project_of(root)
    if not re.fullmatch(r"candidate_[0-9\-]+_[0-9]+\.md", name or ""):
        raise OpError("unsafe candidate name", soft=True)
    path = p.f("outlines", name)
    if path.is_symlink() or not path.is_file():
        raise OpError(f"outlines/{name} is missing or unsafe", soft=True)
    return read_text(path)


def choose_outline(root, name, baseline, *, token=None, events=None):
    """Save a candidate as outline.md: strips only the leading notes comment,
    backs up any previous outline, never touches the candidate file."""
    p = _project_of(root)
    text = read_outline_candidate(root, name)
    _stale_outline(p, baseline)
    if token:
        token.check()
    import re as _re
    body = _re.sub(r"^<!-- notes:.*?-->\n", "", text, flags=_re.S)
    _write_outline(p, body)
    _emit(events, "outline_saved", source=name)
    return {"saved": "outline.md", "source": name, "from_history": False}


def save_outline_body(root, body, baseline, *, token=None, events=None):
    """Commit the edited working body through the same backed-up boundary."""
    p = _project_of(root)
    _stale_outline(p, baseline)
    if token:
        token.check()
    _write_outline(p, body)
    _emit(events, "outline_saved", source="edit")
    return {"saved": "outline.md", "source": "edit", "from_history": False}


def _stale_outline(p, baseline):
    if not isinstance(baseline, dict):
        raise OpError("no captured outline baseline; reload the outline pane "
                      "before saving")
    _stale_check(p, baseline)


def _write_outline(p, body):
    if not _no_symlink_below(p.root, "outlines"):
        raise OpError("outlines/ is a symlink; refusing to back up")
    if not _no_symlink_below(p.root, "outline.md"):
        raise OpError("outline.md is a symlink; refusing to write")
    prev = p.f("outline.md")
    if prev.exists() and not prev.is_symlink():
        dest_name = f"outline_prev_{stamp()}.md"
        dest = p.f("outlines", dest_name)
        n = 1
        while dest.exists():
            n += 1
            dest = p.f("outlines", f"outline_prev_{stamp()}_{n}.md")
        import shutil
        try:
            shutil.copy2(prev, dest)
        except OSError as e:
            raise OpError(f"the outline backup could not be written "
                          f"({type(e).__name__})") from None
    write_text(prev, body)


# ----------------------------------------------------------------- scenes

def scenes_overview(root):
    """Read-only scenes pane state: saved cards, outline, tree membership."""
    p = _project_of(root)
    scenes = _scenes_or_error(p)
    outline = read_text(p.f("outline.md")).strip() \
        if p.f("outline.md").is_file() and not p.f("outline.md").is_symlink() \
        else ""
    trees = []
    d = p.f("trees")
    if d.is_dir() and not d.is_symlink():
        try:
            trees = sorted(x.name for x in d.glob("*.json"))
        except OSError:
            trees = []
    return {"scenes": scenes, "outline": outline, "trees": trees,
            "target_words": int(p.cfg["target_words"]),
            "outline_present": bool(outline)}


def scenes_baseline(root):
    """Captured scene bytes and tree membership for generation/acceptance."""
    p = _project_of(root)
    base = _capture(p, ["scenes.json", "outline.md", "bible.md",
                        "project.json"])
    d = p.f("trees")
    try:
        base["trees"] = tuple(sorted(x.name for x in d.glob("*.json"))) \
            if d.is_dir() and not d.is_symlink() else ()
    except OSError:
        base["trees"] = ()
    return base


def scenes_baseline_stale(root, baseline):
    """True when the captured scenes/tree membership changed externally."""
    try:
        current = scenes_baseline(root)
    except OpError:
        return True
    return any(current[k] != baseline.get(k)
               for k in ("scenes.json", "trees"))


def _normalize_scene_cards(arr, tw):
    """Shared normalization/validation of generated scene cards (design 6):
    CLI defaults and IDs, integer-form numeric strings, recoverable field
    errors instead of ValueError, advisory warnings only."""
    from .prompt import format_card
    if not isinstance(arr, list) or not arr:
        raise OpError("the response is not a nonempty JSON array of scene "
                      "cards", soft=True)
    errors = []
    for k, s in enumerate(arr, 1):
        if not isinstance(s, dict):
            errors.append(f"card {k} is not an object")
    if errors:
        raise OpError("; ".join(errors), soft=True)
    width = 3 if len(arr) > 99 else 2
    out, warnings, total = [], [], 0

    def _field(k, s, name, default=""):
        v = s.get(name, default)
        if v is None:
            v = default
        if not isinstance(v, str):
            raise OpError(f"card {k}: {name} must be text", soft=True)
        return v

    def _strlist(k, s, name):
        v = s.get(name, [])
        if v is None:
            v = []
        if not isinstance(v, list) or \
                any(not isinstance(x, str) for x in v):
            raise OpError(f"card {k}: {name} must be a list of strings",
                          soft=True)
        return list(v)

    for k, s in enumerate(arr, 1):
        chapter = s.get("chapter", 1)
        if isinstance(chapter, str) and chapter.strip().isdigit():
            chapter = int(chapter)   # integer-form numeric strings, as the CLI
        if isinstance(chapter, bool) or not isinstance(chapter, int) or \
                chapter < 1:
            raise OpError(f"card {k}: chapter must be a positive integer",
                          soft=True)
        twv = s.get("target_words", 0) or 0
        if isinstance(twv, str) and twv.strip().isdigit():
            twv = int(twv)
        if isinstance(twv, bool) or not isinstance(twv, int) or twv < 0:
            raise OpError(f"card {k}: target_words must be a nonnegative "
                          "integer", soft=True)
        card = {
            "id": f"s{k:0{width}d}",
            "chapter": chapter,
            "title": _field(k, s, "title"),
            "pov": _field(k, s, "pov"),
            "setting": _field(k, s, "setting"),
            "characters": _strlist(k, s, "characters"),
            "goal": _field(k, s, "goal"),
            "conflict": _field(k, s, "conflict"),
            "outcome": _field(k, s, "outcome"),
            "beats": _strlist(k, s, "beats"),
            "notes": "",
            "target_words": twv,
            "status": "planned",
            "state_updated": False,
        }
        out.append(card)
        total += twv
        if twv == 0:
            warnings.append(f"card {k} targets 0 words")
        for fld in ("title", "pov", "setting", "goal", "conflict", "outcome"):
            if not card[fld]:
                warnings.append(f"card {k} has no {fld}")
        if not card["characters"]:
            warnings.append(f"card {k} lists no characters")
        if not card["beats"]:
            warnings.append(f"card {k} has no beats")
    if tw:
        warnings.append(f"{len(arr)} scenes, {total} target words "
                        f"(project target {tw})")
    return out, warnings, total


def scene_messages(bible, outline, tw):
    """The exact cmd_scenes planner messages (pure)."""
    from .config import PLANNER_SYSTEM
    user = (
        f"# Story bible\n{bible}\n\n# Outline\n{outline}\n\n"
        "Break this outline into scene cards. A scene is one continuous "
        "stretch of time, place and POV.\n"
        "Return a JSON array, no prose, no code fence, between <scenes> and "
        "</scenes> tags (anything outside them is discarded). Each element:\n"
        '{"chapter": int, "title": str, "pov": str, "setting": str, '
        '"characters": [str], '
        '"goal": str, "conflict": str, "outcome": str, "beats": [str], '
        '"target_words": int}\n'
        "\"pov\" is the name of the POV character. \"characters\" lists every "
        "character physically present in the scene, "
        "by name, including the POV character; nobody else.\n"
        f"The target_words values must sum to about {tw}. Cover every beat "
        "of the outline, in order."
    )
    return [{"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": user}]


def generate_scene_cards(root, *, force=False, provider_factory=None,
                         token=None, events=None):
    """Scene-card generation from a saved outline (CLI `scenes`).

    Force protection mirrors `scenes --force`: any non-planned card or any
    tree file requires an explicit confirmation before the provider call
    (declining runs no request and changes nothing). Invalid arrays are saved
    at the existing raw path for inspection; scenes.json is never replaced by
    a preview."""
    p = _project_of(root)
    outline = read_text(p.f("outline.md")).strip() \
        if p.f("outline.md").is_file() else ""
    if not outline:
        raise OpError("outline.md is empty or missing (generate and choose "
                      "an outline first)", soft=True)
    existing = _scenes_or_error(p)
    if existing and not force:
        if any(s.get("status") != "planned" for s in existing) or \
                any(p.f("trees").glob("*.json")):
            raise OpError("scenes are already being drafted; confirm the "
                          "force equivalent to replace scenes.json "
                          "(trees are kept)", soft=True, collision=True)
    baseline = scenes_baseline(root)
    bible = read_text(p.f("bible.md")).strip()
    tw = int(p.cfg["target_words"])
    if token:
        token.check()
    msgs = scene_messages(bible, outline, tw)
    provider = _provider(p, provider_factory)
    _emit(events, "progress", msg="generating scene cards...")
    from .commands import extract_json_array
    from .utils import extract_tagged
    try:
        text, finish, _u = provider.chat(
            "planner", msgs, token=token,
            on_retry_event=None if events is None else (
                lambda why, delay: _emit(events, "retry", why=why,
                                         delay=delay)))
    except Cancelled:
        raise
    except Exception as e:  # noqa: BLE001 — sanitized outcome
        raise OpError(f"scene generation failed: {e}", soft=True) from None
    arr = extract_json_array(text)
    if arr is None or not all(isinstance(x, dict) for x in arr):
        name = f"scenes_raw_{stamp()}.txt"
        if not _no_symlink_below(p.root, "outlines", name):
            raise OpError(f"outlines/{name} is a symlink; refusing to write")
        write_text(p.f("outlines", name), text)
        _emit(events, "scenes_raw_saved", name=name)
        return {"raw": text, "raw_path": name, "finish": finish,
                "cards": None, "warnings": [
                    f"could not parse a JSON array (finish_reason={finish}); "
                    "raw output saved"], "baseline": baseline,
                "total": None, "target": tw}
    cards, warnings, total = _normalize_scene_cards(arr, tw)
    _emit(events, "scene_cards_previewed", count=len(cards))
    return {"raw": None, "raw_path": None, "finish": finish, "cards": cards,
            "warnings": warnings, "total": total, "target": tw,
            "baseline": baseline}


def _scenes_cards_text(cards):
    from .prompt import format_card
    return "\n\n".join(format_card(dict(s, id=f"#{k}"))
                       for k, s in enumerate(cards, 1))


def accept_scene_cards(root, cards, baseline, *, token=None, events=None):
    """Explicit acceptance of a validated preview: backs up the previous
    scenes.json as outlines/scenes_prev_<stamp>.json (existing nonempty list
    only), then saves. Trees are never touched."""
    p = _project_of(root)
    _scenes_or_error(p)
    out, warnings, _total = _normalize_scene_cards(cards,
                                                   int(p.cfg["target_words"]))
    if not _no_symlink_below(p.root, "scenes.json"):
        raise OpError("scenes.json is a symlink; refusing to write")
    if not _no_symlink_below(p.root, "outlines"):
        raise OpError("outlines/ is a symlink; refusing to back up")
    if token:
        token.check()
    _stale_check(p, {"scenes.json": baseline["scenes.json"]})
    current = _scenes_or_error(p)
    if current:
        dest_name = f"scenes_prev_{stamp()}.json"
        dest = p.f("outlines", dest_name)
        n = 1
        while dest.exists():
            n += 1
            dest = p.f("outlines", f"scenes_prev_{stamp()}_{n}.json")
        import shutil
        try:
            shutil.copy2(p.f("scenes.json"), dest)
        except OSError as e:
            raise OpError(f"the scenes backup could not be written "
                          f"({type(e).__name__})") from None
    from .utils import write_json
    write_json(p.f("scenes.json"), out)
    _emit(events, "scene_cards_accepted", count=len(out))
    return {"saved": len(out), "warnings": warnings,
            "scene_ids": [c["id"] for c in out],
            "backup": "outlines/scenes_prev_<stamp>.json" if current
            else None}


# ------------------------------------------------------------------ open

_SAFE_JSON_FILES = ("project.json", "scenes.json", "summaries.json")
_INIT_FILE_NAMES = tuple(INIT_FILES)


def _safe_read_json(path, warnings, label):
    if path.is_symlink():
        warnings.append(f"{label} is a symlink and was not read")
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        warnings.append(f"{label} is missing or not valid JSON")
        return None
    if not isinstance(raw, dict) and label == "project.json":
        warnings.append(f"{label} is not a JSON object")
        return None
    return raw


def project_overview(root):
    """Read-only sanitized setup view for the Setup pane (no writes, no calls).

    Works for missing directories, empty directories and invalid configs; the
    only credential facts are the environment name and boolean availability —
    an existing inline api_key is never echoed or migrated.
    """
    root = canonical_root(root)
    out = {"root": str(root), "exists": root.is_dir(), "config_ok": False,
           "title": "", "target_words": 0, "scenes": 0, "scene_status": [],
           "preset_found": False, "preset_path": "", "api_key_env": "",
           "env_set": False, "inline_key": False, "creds_ok": False,
           "outline_present": False, "trees": [], "created_files": [],
           "missing_files": [], "dirs": [], "warnings": []}
    if not out["exists"]:
        out["warnings"].append("the directory does not exist yet; "
                               "use Create to initialize it")
        return out
    warnings = out["warnings"]
    missing = [n for n in _INIT_FILE_NAMES
               if not _plain_file(root / n)]
    out["missing_files"] = missing
    out["created_files"] = [n for n in _INIT_FILE_NAMES
                            if _plain_file(root / n)]
    out["dirs"] = [d for d in INIT_DIRS if (root / d).is_dir()]
    raw = _safe_read_json(root / "project.json", warnings, "project.json")
    if raw is None:
        out["warnings"] = warnings
        return out
    out["config_ok"] = True
    cfg = deep_merge(DEFAULT_CONFIG, raw)
    out["title"] = str(cfg.get("title", ""))
    out["target_words"] = cfg.get("target_words", 0)
    scenes_raw = _safe_read_json(root / "scenes.json", warnings, "scenes.json")
    if isinstance(scenes_raw, list):
        out["scenes"] = len(scenes_raw)
        out["scene_status"] = [str(s.get("status", ""))
                               for s in scenes_raw if isinstance(s, dict)]
    out["outline_present"] = (root / "outline.md").is_file()
    trees = root / "trees"
    if trees.is_dir() and not trees.is_symlink():
        try:
            out["trees"] = sorted(p.name for p in trees.glob("*.json"))
        except OSError:
            warnings.append("trees/ could not be listed")
    env = str(cfg.get("api_key_env") or "")
    out["api_key_env"] = env
    out["env_set"] = bool(env) and bool(os.environ.get(env, "").strip())
    out["inline_key"] = bool(str(cfg.get("api_key") or "").strip())
    out["creds_ok"] = out["inline_key"] or out["env_set"]
    preset = str(cfg.get("roles", {}).get("writer", {}).get("preset", "")
                 or "writer_preset.json")
    ppath = Path(preset).expanduser()
    if not ppath.is_absolute():
        if _escapes(root, ppath):
            warnings.append("the configured writer preset path is unsafe; "
                            "it was not read")
            ppath = None
        else:
            ppath = root / ppath
    if ppath is not None:
        out["preset_path"] = str(ppath)
        out["preset_found"] = ppath.is_file()
    out["warnings"] = warnings
    return out


def _plain_file(path):
    try:
        return path.is_file() and not path.is_symlink()
    except OSError:
        return False


def _escapes(root, rel):
    try:
        (root / rel).resolve().relative_to(root)
    except (OSError, ValueError):
        return True
    return False


# -------------------------------------------------------------- settings

_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_HTTP_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+/?")

_CONSUMED_OVERRIDES = ("temp", "top_p", "top_k", "min_p", "rep_pen",
                       "freq_pen", "presence_pen", "genamt", "max_length",
                       "dry_multiplier", "dry_base", "dry_allowed_length",
                       "dry_sequence_breakers", "dry_penalty_last_n")

CHAT_ROLES = ("planner", "summarizer", "critic", "editor")
CHAT_SAMPLERS = ("temperature", "top_p", "top_k", "min_p",
                 "repetition_penalty", "presence_penalty", "frequency_penalty",
                 "min_tokens", "max_tokens")


def _setting_fields():
    """The explicit allowlist of supported nonsecret fields (design 3)."""
    f = []
    a = f.append
    a(("title", "Title", "text"))
    a(("target_words", "Target words", "posint"))
    a(("api_base", "API base URL", "url"))
    a(("api_key_env", "API key environment variable NAME", "envname"))
    a(("max_context_fallback", "Max context fallback", "posint"))
    a(("context_safety_margin", "Context safety margin [0,1)", "margin"))
    a(("prompt_budget", "Prompt budget (tokens)", "posint"))
    a(("chars_per_token_default", "Chars per token (estimation ratio)", "posnum"))
    a(("max_parallel", "Max parallel requests", "posint"))
    a(("request_timeout_s", "Request timeout (s)", "posnum"))
    for role in ("planner", "writer", "summarizer", "critic", "editor"):
        a((f"roles.{role}.model", f"{role} model", "nonblank"))
        if role == "writer":
            a(("roles.writer.preset", "Writer preset path", "nonblank"))
            a(("roles.writer.swipes", "Writer swipes", "posint"))
            a(("roles.writer.passage_words", "Passage words", "posint"))
            a(("roles.writer.user_name", "User name", "text"))
            a(("roles.writer.absent_character_lore",
               "Absent-character lore", "enum:reference|exclude"))
            a(("roles.writer.lore_match_whole_words",
               "Lore matches whole words", "bool"))
            for k in _CONSUMED_OVERRIDES:
                a((f"roles.writer.preset_overrides.{k}",
                   f"Writer preset override: {k}", _override_kind(k)))
        else:
            for k in CHAT_SAMPLERS:
                a((f"roles.{role}.{k}", f"{role} {k}", _sampler_kind(k)))
            a((f"roles.{role}.thinking", f"{role} thinking", "bool"))
            a((f"roles.{role}.thinking_budget", f"{role} thinking budget",
               "nonnegint"))
    for k in ("bible", "scene_card", "summary", "state", "lore", "recent",
              "steer"):
        a((f"budget_tokens.{k}", f"Budget {k} (tokens)", "nonnegint"))
    for k in ("detailed_recent_scenes", "detailed_words", "brief_words",
              "arc_words"):
        a((f"summary.{k}", f"Summary {k}", "nonnegint"))
    a(("banned_phrases", "Banned phrases (one per line)", "lines"))
    a(("ngram.n", "Repeated n-gram size n", "posint"))
    a(("ngram.min_count", "Repeated n-gram min count", "posint"))
    a(("ngram.top", "Repeated n-gram top list size", "posint"))
    return f


def _override_kind(k):
    if k in ("top_k", "dry_allowed_length", "dry_penalty_last_n", "genamt",
             "max_length"):
        return "nonnegint"
    if k in ("dry_sequence_breakers",):
        return "lines"
    if k in ("rep_pen", "dry_base"):
        return "posnum"
    if k in ("temp", "dry_multiplier"):
        return "nonnegnum"
    if k in ("top_p", "min_p", "freq_pen", "presence_pen"):
        return "prob01" if k in ("top_p", "min_p") else "num"
    return "num"


def _sampler_kind(k):
    if k in ("top_k", "min_tokens"):
        return "nonnegint"
    if k == "max_tokens":
        return "posint"
    if k in ("temperature", "dry_multiplier"):
        return "nonnegnum"
    if k in ("top_p", "min_p"):
        return "prob01"
    if k == "repetition_penalty":
        return "posnum"
    return "num"


SETTING_FIELDS = _setting_fields()
_SETTING_PATHS = {path for path, _label, _kind in SETTING_FIELDS}


def _nested(d, dotted):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _get_setting(cfg, dotted):
    v = _nested(cfg, dotted)
    return "" if v is None else v


def settings_state(root):
    """Read-only settings view: supported values (merged with defaults),
    credential name/availability booleans, ignored-sampler warnings and the
    unknown fields the patch must preserve. Never includes a key value."""
    root = canonical_root(root)
    p = _project_of(root)
    raw = _read_bytes(p.f("project.json"), "project.json")
    try:
        parsed = json.loads(raw.decode("utf-8")) if raw is not None else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise OpError("project.json is not valid JSON") from None
    if not isinstance(parsed, dict):
        raise OpError("project.json is not a JSON object")
    from .utils import deep_merge
    cfg = deep_merge(DEFAULT_CONFIG, parsed)
    values = {path: _get_setting(cfg, path) for path, _l, _k in SETTING_FIELDS}
    values = _display_values(cfg, parsed)
    warnings = []
    rc = cfg["roles"]["writer"]
    stale = [k for k in ("temperature", "top_p", "top_k", "min_p",
                         "repetition_penalty", "presence_penalty",
                         "frequency_penalty", "seed", "stop", "min_tokens",
                         "max_tokens") if k in rc]
    if stale:
        warnings.append("writer keys " + ", ".join(stale) +
                        " in project.json are ignored: writer samplers come "
                        "from the preset")
    extras = sorted(set((rc.get("preset_overrides") or {})) - set(_CONSUMED_OVERRIDES))
    if extras:
        warnings.append("writer preset override keys " + ", ".join(extras) +
                        " are preserved but have no control here (not sent "
                        "to the provider)")
    unknown = _unknown_paths(parsed)
    env = str(cfg.get("api_key_env") or "")
    state = {"root": str(root), "values": values, "warnings": warnings,
             "unknown_fields": unknown, "api_key_env": env,
             "env_set": bool(env) and bool(os.environ.get(env, "").strip()),
             "inline_key": bool(str(cfg.get("api_key") or "").strip()),
             "env_value": os.environ.get(env, "") if env else ""}
    state["creds_ok"] = state["inline_key"] or state["env_set"]
    return state


def _display_values(cfg, parsed):
    """Values to show: merged with defaults for every supported control;
    Save commits only touched fields, so untouched defaults are never
    materialized into project.json."""
    return {path: _get_setting(cfg, path) for path, _l, _k in SETTING_FIELDS}


def _unknown_paths(parsed, prefix=""):
    out = []
    for k, v in parsed.items():
        dotted = f"{prefix}{k}"
        if dotted in _SETTING_PATHS or (prefix.startswith("roles.") and
                                        dotted.endswith(".model")):
            if isinstance(v, dict) and dotted not in _SETTING_PATHS:
                out += _unknown_paths(v, dotted + ".")
            continue
        if isinstance(v, dict):
            out += _unknown_paths(v, dotted + ".")
        else:
            out.append(dotted)
    return out


def _parse_raw(kind, text):
    """Parse one form string into a typed value; returns (value, error).
    None value means 'unset' (remove the key)."""
    text = (text or "").strip()
    if kind == "bool":
        if text in ("", "false", "False", "no"):
            return False, None
        if text in ("true", "True", "yes"):
            return True, None
        return None, "must be true or false"
    if kind == "enum:reference|exclude":
        if text in ("reference", "exclude"):
            return text, None
        return None, "must be 'reference' or 'exclude'"
    if kind == "lines":
        items = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        return items, None
    if kind in ("text", "nonblank", "url", "envname"):
        if kind == "nonblank" and not text:
            return None, "must not be blank"
        if kind == "envname":
            if not _ENV_NAME_RE.fullmatch(text or ""):
                return None, ("must be the NAME of an environment variable "
                              "(letters, digits, underscores)")
            return text, None
        if kind == "url":
            if not text.startswith(("http://", "https://")):
                return None, "must be an http(s) URL"
            rest = text.split("://", 1)[1]
            if "@" in rest.split("/", 1)[0] or "?" in text or "#" in text:
                return None, "must not contain userinfo, query or fragment"
            if not rest:
                return None, "must be an http(s) URL"
            return text, None
        return text, None
    # numeric kinds
    num_error = "must be a finite number"
    try:
        v = float(text)
    except ValueError:
        return None, num_error
    if v != v or v in (float("inf"), float("-inf")):
        return None, num_error
    if kind == "posint":
        if v != int(v) or v < 1:
            return None, "must be a positive integer"
        return int(v), None
    if kind == "nonnegint":
        if v != int(v) or v < 0 or isinstance(v, bool):
            return None, "must be a nonnegative integer"
        return int(v), None
    if kind == "posnum":
        if v <= 0:
            return None, "must be a positive number"
        return v, None
    if kind == "nonnegnum":
        if v < 0:
            return None, "must be a nonnegative number"
        return v, None
    if kind == "margin":
        if not 0 <= v < 1:
            return None, "must be in [0, 1)"
        return v, None
    if kind == "prob01":
        if not 0 <= v <= 1:
            return None, "must be in [0, 1]"
        return v, None
    if kind == "num":
        return v, None
    return None, f"unsupported field kind {kind}"


def validate_settings(values):
    """Local domain validation of {path: raw-string-or-None}; returns a list
    of 'path: message' errors. None values (unset) are always allowed."""
    errors = []
    for path, raw in values.items():
        if raw is None:
            continue
        field = next((f for f in SETTING_FIELDS if f[0] == path), None)
        if field is None:
            errors.append(f"{path}: unsupported field")
            continue
        _path, _label, kind = field
        if kind == "lines":
            continue  # any multiline text is a list of strings
        _v, err = _parse_raw(kind, raw if isinstance(raw, str) else str(raw))
        if err:
            errors.append(f"{path}: {err}")
    # min_tokens <= max_tokens per chat role
    for role in CHAT_ROLES:
        mn, mx = values.get(f"roles.{role}.min_tokens"), values.get(
            f"roles.{role}.max_tokens")
        def _num(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return None
        if mn is not None and mx is not None:
            a, b = _num(mn), _num(mx)
            if a is not None and b is not None and a > b:
                errors.append(f"roles.{role}.min_tokens: min_tokens must not "
                              "exceed max_tokens")
    return errors


def settings_baseline(root):
    """Opaque baseline for a settings edit session: exact project.json bytes."""
    root = canonical_root(root)
    p = _project_of(root)
    return _capture(p, ["project.json"])


def save_settings(root, values, *, baseline=None, token=None, events=None):
    """Validate and commit a settings patch over the original JSON object.

    Only the given paths change; unknown fields and any existing inline
    api_key are preserved opaquely. A path mapped to None removes that key
    (unset). Refusing leaves disk unchanged."""
    errors = validate_settings(values)
    if errors:
        raise OpError("settings were not saved: " + "; ".join(errors))
    root = canonical_root(root)
    p = _project_of(root)
    if baseline is None:
        baseline = _capture(p, ["project.json"])
    if token:
        token.check()
    raw = baseline["project.json"]
    try:
        parsed = json.loads(raw.decode("utf-8")) if raw is not None else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise OpError("project.json is not valid JSON; not saved") from None
    if not isinstance(parsed, dict):
        raise OpError("project.json is not a JSON object; not saved")
    changed, cleared = [], []
    for path, value in values.items():
        parts = path.split(".")
        cur = parsed
        for part in parts[:-1]:
            nxt = cur.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[part] = nxt
            cur = nxt
        leaf = parts[-1]
        if value is None or value == "":
            if leaf in cur:
                del cur[leaf]
                cleared.append(path)
            continue
        field = next((f for f in SETTING_FIELDS if f[0] == path), None)
        if field is None:
            raise OpError(f"{path}: unsupported field")
        _p, _label, kind = field
        if kind == "lines":
            items = [ln.strip() for ln in str(value).splitlines()
                     if ln.strip()]
            cur[leaf] = items
        else:
            v, err = _parse_raw(kind, str(value))
            if err:
                raise OpError(f"settings were not saved: {path}: {err}")
            cur[leaf] = v
        changed.append(path)
    _stale_check(p, baseline)
    write_text(p.f("project.json"), json.dumps(parsed, indent=2,
                                               ensure_ascii=False) + "\n")
    _advance(p, baseline, "project.json")
    _emit(events, "settings_saved", saved=len(changed))
    return {"saved": changed, "cleared": cleared,
            "warnings": settings_state(root)["warnings"]}


# ---------------------------------------------------------------- limits

_SECRET_KEY_RE = re.compile(r"api[-_]?key|secret|authorization|bearer",
                            re.I)


def _scrub_text(p, text):
    """Remove resolved credential values from provider text (GUI only)."""
    key = str(p.cfg.get("api_key") or "").strip()
    env = str(p.cfg.get("api_key_env") or "")
    envval = os.environ.get(env, "").strip() if env else ""
    out = text or ""
    for secret in (key, envval):
        if secret:
            out = out.replace(secret, "[redacted]")
    return out


def _sanitize_raw(obj, p=None):
    """Drop credential-ish keys and scrub resolved secrets from model
    metadata before GUI display (limits.json keeps the CLI shape)."""
    if isinstance(obj, dict):
        return {k: _sanitize_raw(v, p) for k, v in obj.items()
                if not _SECRET_KEY_RE.search(str(k))}
    if isinstance(obj, list):
        return [_sanitize_raw(x, p) for x in obj]
    if isinstance(obj, str) and p is not None:
        return _scrub_text(p, obj)
    return obj


def _first_int(d, keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, int) and v > 0:
            return v
    return None


def fetch_limits(root, *, provider_factory=None, token=None, events=None):
    """Explicit limits fetch through the shared Api (CLI `limits`).

    One /plan request and one /models/<id> lookup per distinct configured
    model; 404 is a found:false result, transport/plan/unexpected failures or
    Stop keep the previous limits.json. The saved shape matches cmd_limits."""
    p = _project_of(root)
    key = str(p.cfg.get("api_key") or "").strip()
    env = str(p.cfg.get("api_key_env") or "")
    if not key and not (env and os.environ.get(env, "").strip()):
        raise OpError(
            f'no API key: set "api_key" in project.json, or export {env}=...',
            soft=True)
    provider = _provider(p, provider_factory)
    baseline = _capture(p, ["project.json", "limits.json"])
    if token:
        token.check()

    plan = None
    try:
        plan = provider.get("/plan", token=token,
                            on_retry_event=None if events is None else (
                                lambda why, delay: _emit(events, "retry",
                                                         why=why, delay=delay)))
    except Cancelled:
        raise
    except Exception as e:  # noqa: BLE001 — sanitized outcome, file untouched
        raise OpError(f"limits fetch failed: {_scrub_text(p, str(e))}",
                      soft=True) from None
    out = {"fetched": now(), "plan": plan, "models": {}}
    _emit(events, "plan_fetched", plan_max=(
        plan.get("max_context_length") if isinstance(plan, dict) else None))
    for role, rc in p.cfg["roles"].items():
        mid = rc["model"]
        if mid in out["models"]:
            continue
        if token:
            token.check()
        try:
            entry = provider.get("/models/" + mid, token=token,
                                 on_retry_event=None if events is None else (
                                     lambda why, delay: _emit(events, "retry",
                                                              why=why,
                                                              delay=delay)))
        except HttpErr as e:
            if e.status == 404:
                entry = None   # a model 404 is a found:false result
            else:
                raise OpError(f"limits fetch failed: "
                              f"{_scrub_text(p, str(e))}", soft=True) from None
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            raise OpError(f"limits fetch failed: {_scrub_text(p, str(e))}",
                          soft=True) from None
        if isinstance(entry, dict) and "id" not in entry and entry.get("data"):
            d = entry["data"]
            entry = d[0] if isinstance(d, list) and d else (
                d if isinstance(d, dict) else None)
        if not isinstance(entry, dict):
            out["models"][mid] = {"found": False}
        else:
            out["models"][mid] = {
                "found": True,
                "context": _first_int(entry, ("context_length",
                                              "max_context_length",
                                              "context_size", "max_model_len",
                                              "context_window")),
                "max_completion": _first_int(entry, ("max_completion_tokens",
                                                     "max_output_tokens")),
                "available_on_current_plan": entry.get(
                    "available_on_current_plan"),
                "raw": entry,
            }
    if token:
        token.check()
    _stale_check(p, baseline)
    from .utils import write_json
    write_json(p.f("limits.json"), out)
    _advance(p, baseline, "limits.json")
    view = {"fetched": out["fetched"],
            "plan_max_context": (plan.get("max_context_length")
                                 if isinstance(plan, dict) else None),
            "plan_concurrency": (plan.get("concurrency")
                                 if isinstance(plan, dict) else None),
            "roles": []}
    for role, rc in p.cfg["roles"].items():
        m = out["models"][rc["model"]]
        view["roles"].append({
            "role": role, "model": rc["model"], "found": m["found"],
            "context": m.get("context"), "max_completion": m.get("max_completion"),
            "available": m.get("available_on_current_plan"),
            "raw": _sanitize_raw(m.get("raw"), p) if m["found"] else None,
        })
    _emit(events, "limits_saved")
    return {"saved": str(p.f("limits.json")), "view": view,
            "not_found": [k for k, v in out["models"].items() if not v["found"]]}

