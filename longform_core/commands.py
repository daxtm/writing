"""Command implementations and interactive helpers."""

import json
import re
import shutil
from pathlib import Path

import httpx

from .api import Api, HttpErr, NoAnswerErr
from .checks import check_report
from .config import (BIBLE_TEMPLATE, CRITIC_SYSTEM, DEFAULT_CONFIG, EDITOR_SYSTEM, PLANNER_SYSTEM, SAMPLING_KEYS, STATE_TEMPLATE, SUMMARIZER_SYSTEM)
from .lore import is_present, Lore, pov_name
from .prompt import (build_writer_prompt, clean_continuation, format_card, layered_summary, print_report,
                     tail_trim_chars)
from .tree import Tree
from .utils import (ask, col, die, edit_saved, extract_tagged, keep_lead, line_diff, now, page, parse_sections, read_json, read_text, save_input, slug, stamp, tag_instr, text_hash, warn, word_diff, words, write_json, write_text)

def cmd_init(args):
    root = Path(args.dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    made = []
    files = {
        "project.json": json.dumps(DEFAULT_CONFIG, indent=2) + "\n",
        "bible.md": BIBLE_TEMPLATE,
        "state.md": STATE_TEMPLATE,
        "scenes.json": "[]\n",
        "summaries.json": json.dumps({"scenes": {}, "arcs": []}, indent=2) + "\n",
    }
    for name, content in files.items():
        path = root / name
        if not path.exists():
            write_text(path, content)
            made.append(name)
    for d in ("trees", "outlines", "critiques", "checks", "state_history", "lorebooks", "bible_history"):
        (root / d).mkdir(exist_ok=True)
    if args.preset:
        src = Path(args.preset).expanduser().resolve()
        dst = root / "writer_preset.json"
        if not src.exists():
            die(f"preset file not found: {src}")
        if dst.exists():
            warn(f"{dst} already exists; not overwritten")
        else:
            d = read_json(src)
            for k in ("instruct", "context", "sysprompt", "preset"):
                if k not in d:
                    die(f"{src} is not a SillyTavern master export (missing '{k}')")
            shutil.copy2(src, dst)
            made.append("writer_preset.json")
    print(f"project: {root}")
    print("created: " + (", ".join(made) if made else "(nothing; all files already exist)"))
    print("next: set models in project.json, fill in bible.md, put lorebooks in lorebooks/, then run limits")


def cmd_limits(p, args):
    api = Api(p)
    plan = api.get("/plan")
    out = {"fetched": now(), "plan": plan, "models": {}}

    def first_int(d, keys):
        for k in keys:
            v = d.get(k)
            if isinstance(v, int) and v > 0:
                return v
        return None

    print(col("plan:", "36"), json.dumps(plan))
    for role, rc in p.cfg["roles"].items():
        mid = rc["model"]
        if mid not in out["models"]:
            try:
                entry = api.get("/models/" + mid)
            except HttpErr as e:
                if e.status != 404:
                    raise
                entry = None
            if isinstance(entry, dict) and "id" not in entry and entry.get("data"):
                d = entry["data"]
                entry = d[0] if isinstance(d, list) and d else (d if isinstance(d, dict) else None)
            if not isinstance(entry, dict):
                out["models"][mid] = {"found": False}
            else:
                out["models"][mid] = {
                    "found": True,
                    "context": first_int(entry, ("context_length", "max_context_length", "context_size", "max_model_len", "context_window")),
                    "max_completion": first_int(entry, ("max_completion_tokens", "max_output_tokens")),
                    "available_on_current_plan": entry.get("available_on_current_plan"),
                    "raw": entry,
                }
        m = out["models"][mid]
        if not m["found"]:
            print(col(f"{role:<10} {mid}: NOT FOUND on Featherless (check the exact id)", "31"))
            continue
        print(f"{role:<10} {mid}")
        print(f"           model context {m['context']}, max completion {m['max_completion']}, "
              f"available on your plan: {m['available_on_current_plan']}")
        if m["available_on_current_plan"] is False:
            print(col("           not available on your current plan", "31"))
        print(f"           raw: {json.dumps(m['raw'])[:400]}")
    write_json(p.f("limits.json"), out)
    plan_max = plan.get("max_context_length") if isinstance(plan, dict) else None
    print(f"plan max_context_length: {plan_max}; concurrency: {plan.get('concurrency') if isinstance(plan, dict) else '?'}")
    print(f"wrote {p.f('limits.json')}")


BIBLE_QUESTIONS = {
    "title": [
        ("Title", "Working title?"),
    ],
    "premise": [
        ("About", "Who is the story about (main character or characters)?"),
        ("Wants", "What do they want?"),
        ("Obstacle", "What stands in their way?"),
        ("Stakes", "What is at stake if they fail?"),
        ("Ending", "How does it end, or which direction should it head? (blank if undecided)"),
    ],
    "source & canon": [
        ("Source", "Fandom / source material? (blank if this is original fiction)"),
        ("Place in canon", "Where in canon does this sit (after which events, season, book or arc)?"),
        ("Canon facts relied on", "Which canon facts does the story rely on (relationships, powers, timeline, places)? List them."),
        ("Changes from canon", "What does your story deliberately change from canon?"),
        ("State outright", "Any canon details models tend to get wrong that should be stated outright?"),
    ],
    "pov & tense": [
        ("Point of view", "Point of view: first person, close third, or something else?"),
        ("Tense", "Tense: past or present?"),
        ("POV character", "One POV character for the whole story, or POV chosen per scene? If one, who?"),
    ],
    "style rules": [
        ("Voice", "What should the prose voice feel like (e.g. wry, lush, sparse)? Any authors to sound like?"),
        ("Dialogue vs narration", "Balance of dialogue vs narration?"),
        ("Explicitness", "How explicit should sex and violence be?"),
        ("Rhythm", "Sentence and paragraph rhythm preferences?"),
        ("Formatting", "How should dialogue and inner thoughts be formatted? (the writer preset defaults to dialogue in quotes, thoughts in italics)"),
        ("Show vs summarize", "What should be shown in full vs summarized (travel, time skips, routine actions)?"),
        ("Always", "Anything else the prose must always do?"),
    ],
    "avoid": [
        ("Tropes", "Tropes you don't want?"),
        ("Habits", "Writing habits you don't want (e.g. characters narrating their feelings, purple prose)?"),
        ("Never use", "Specific words or phrases to never use? (also add them to banned_phrases in project.json so check counts them)"),
    ],
}

CHAR_FIELDS = (("Role", "Role: "), ("Relationships", "Relationships to the others: "), ("Voice", "Voice / how they speak: "))
OTHER_CHARS = "Other characters not in your lorebooks (one per line: name - role - relationships - voice):"


def bible_form(heading, char_names):
    head = (f"# Section: {heading}\n# Answer under each question. Leave an answer blank to skip it.\n"
            "# Your answers go into bible.md as you write them. Lines starting with # are ignored.\n\n")
    key = heading.lower()
    if key == "characters":
        blocks = []
        for name in char_names:
            blocks.append(f"Character: {name}  (from your lorebooks; keep this exact name)\n"
                          + "".join(f"{prompt}\n" for _, prompt in CHAR_FIELDS))
        blocks.append("Character: \n" + "".join(f"{prompt}\n" for _, prompt in CHAR_FIELDS))
        blocks.append(OTHER_CHARS + "\n")
        return head + "\n".join(blocks) + "\nOther notes: \n"
    qs = BIBLE_QUESTIONS.get(key, [("", "What should this section say?")])
    return head + "\n\n".join(f"Q{i}. {q}\nA: " for i, (_, q) in enumerate(qs, 1)) + "\n\nOther notes: \n"


def _clean(lines):
    return "\n".join(lines).strip()


def compose_section(heading, form):
    """Turn a filled-in form into the section body, using your answers exactly as written."""
    lines = [ln.rstrip() for ln in form.splitlines() if not ln.lstrip().startswith("#")]
    key = heading.lower()
    out = []
    if key == "characters":
        chars, cur, field, others, notes, mode = [], None, None, [], [], None
        for ln in lines:
            m = re.match(r"^Character:\s*(.*?)\s*(\(from your lorebooks.*\))?\s*$", ln)
            if m:
                cur = {"name": m.group(1).strip(), "fields": {}}
                chars.append(cur)
                field, mode = None, "char"
                continue
            if ln.startswith(OTHER_CHARS):
                mode, field = "others", None
                continue
            if ln.startswith("Other notes:"):
                mode = "notes"
                rest = ln[len("Other notes:"):].strip()
                if rest:
                    notes.append(rest)
                continue
            if mode == "char" and cur is not None:
                hit = next(((lab, pr) for lab, pr in CHAR_FIELDS if ln.startswith(pr.strip())), None)
                if hit:
                    field = hit[0]
                    cur["fields"][field] = [ln[len(hit[1].strip()):].strip()]
                elif field:
                    cur["fields"][field].append(ln)
            elif mode == "others":
                if ln.strip():
                    others.append(ln.strip())
            elif mode == "notes":
                notes.append(ln)
        for c in chars:
            vals = {k: _clean(v) for k, v in c["fields"].items()}
            if not c["name"] and not any(vals.values()):
                continue
            block = [f"### {c['name'] or '(unnamed)'}"]
            block += [f"- {lab}: {vals[lab]}" for lab, _ in CHAR_FIELDS if vals.get(lab)]
            out.append("\n".join(block))
        if others:
            out.append("### Others\n" + "\n".join(f"- {o}" for o in others))
        if _clean(notes):
            out.append(_clean(notes))
        return "\n\n".join(out).strip()
    qs = BIBLE_QUESTIONS.get(key, [("", "What should this section say?")])
    answers, cur, notes = {}, None, []
    for ln in lines:
        mq = re.match(r"^Q(\d+)\.\s", ln)
        if mq:
            cur = int(mq.group(1))
            answers[cur] = []
            continue
        if ln.startswith("Other notes:"):
            cur = "notes"
            rest = ln[len("Other notes:"):].strip()
            if rest:
                notes.append(rest)
            continue
        if cur == "notes":
            notes.append(ln)
        elif cur is not None:
            answers[cur].append(ln[2:].strip() if ln.startswith("A:") and not answers[cur] else ln)
    for i, (label, _) in enumerate(qs, 1):
        a = _clean(answers.get(i, []))
        if not a:
            continue
        if key == "title" or not label:
            out.append(a)
        elif "\n" in a:
            out.append(f"- {label}:\n" + "\n".join("  " + x if x.strip() else x for x in a.splitlines()))
        else:
            out.append(f"- {label}: {a}")
    if _clean(notes):
        out.append(_clean(notes))
    return "\n".join(out).strip()


def split_bible(text):
    """Returns (preamble, [(heading, body), ...]) for '## ' sections."""
    parts = re.split(r"^## +(.+?)\s*$", text, flags=re.M)
    pre = parts[0]
    secs = [(parts[k].strip(), parts[k + 1].strip("\n")) for k in range(1, len(parts) - 1, 2)]
    return pre, secs


def join_bible(pre, secs):
    out = pre.rstrip("\n") + "\n\n" if pre.strip() else ""
    out += "\n\n".join(f"## {h}\n{b.strip()}" for h, b in secs)
    return out.rstrip() + "\n"


def is_placeholder(body):
    lines = [ln.strip() for ln in body.strip().splitlines() if ln.strip()]
    return not lines or all(re.fullmatch(r"[-*]?\s*\(.*\)|[-*]|###\s*NAME|-\s*[A-Za-z /]+:\s*", ln) for ln in lines)


def cmd_bible(p, args):
    path = p.f("bible.md")
    text = read_text(path) or BIBLE_TEMPLATE
    pre, secs = split_bible(text)
    if not secs:
        die(f"{path} has no '## ' sections to work through")
    if path.exists():
        p.f("bible_history").mkdir(exist_ok=True)
        shutil.copy2(path, p.f("bible_history", f"bible_{stamp()}.md"))
    lore = Lore(p, p.scenes())
    char_names = [lore.char_name(f, m) for f, m in lore.books() if m.get("kind") == "character"]
    print(f"{len(secs)} sections. Answer each section's questions in $EDITOR; your answers go into the bible as written.")
    for k, (heading, body) in enumerate(secs):
        current = "(empty / template placeholder)" if is_placeholder(body) else body.strip()
        print(col(f"\n=== [{k + 1}/{len(secs)}] {heading} ===", "36"))
        print(f"current:\n{current}\n")
        c = ask("[Enter] answer this section / [s]kip / [q]uit: ").strip().lower()
        if c.startswith("q"):
            break
        if c.startswith("s"):
            continue
        akind = f"bible_answers_{slug(heading)}"
        saved = p.f("inputs", f"{akind}.md")
        if saved.exists():
            form = read_text(saved)
            print(f"loaded your saved answers from {saved}")
        else:
            form = bible_form(heading, char_names)
        while True:
            form = edit_saved(p, akind, form)
            section = compose_section(heading, form)
            print(col(f"\n--- {heading} ({words(section)} words) ---", "36"))
            print(section or "(empty)")
            c = ask("\n[a]ccept / [e]dit answers / [s]kip section / [q]uit: ").strip().lower()
            if c.startswith("e"):
                continue
            if c.startswith("a"):
                secs[k] = (heading, section)
                write_text(path, join_bible(pre, secs))
                print(f"saved {heading} to {path}")
            if c.startswith("q"):
                print(f"bible: {path}")
                return
            break
    model = p.cfg["roles"]["writer"]["model"]
    t = p.est(model, read_text(path))
    budget = int(p.cfg["budget_tokens"]["bible"])
    print(f"\nbible: {path}  ~{t} tokens (budget {budget})")
    if t > budget:
        warn("over budget: shorten the longest sections or move detail into lorebooks")


OUTLINE_NOTES_FORM = ("# Notes for the outline: anything you want the planner to follow (pacing, key events, the ending, tone).\n"
                      "# Lines starting with # are ignored. Leave empty for no notes.\n\n")


def cmd_outline(p, args):
    bible = read_text(p.f("bible.md")).strip()
    tw = int(p.cfg["target_words"])
    lo, hi = max(1, tw // 1500), max(2, tw // 800)
    notes_file = p.f("inputs", "outline_notes.md")
    if args.notes:
        save_input(p.root, "outline_notes", OUTLINE_NOTES_FORM + args.notes + "\n")
    raw_notes = read_text(notes_file) if notes_file.exists() else OUTLINE_NOTES_FORM

    def notes_text():
        return "\n".join(ln for ln in raw_notes.splitlines() if not ln.lstrip().startswith("#")).strip()

    def make_msgs(notes):
        user = (
            f"# Story bible\n{bible}\n\n"
            + (f"# Author's notes for this outline (follow them)\n{notes}\n\n" if notes else "")
            + f"Design a complete outline for a story of about {tw} words.\n"
            "Format (markdown):\n"
            "- Parts/acts, then chapters, then numbered beats per chapter.\n"
            "- Every beat is a concrete event: who does what, what changes.\n"
            "- Give each chapter an approximate word count; the counts must sum to roughly the target.\n"
            f"- A {tw}-word story has room for roughly {lo}-{hi} scenes; pace accordingly.\n"
            "- End with a section 'Threads & payoffs' listing each setup and the beat where it pays off.\n"
            + tag_instr("outline")
        )
        return [{"role": "system", "content": PLANNER_SYSTEM}, {"role": "user", "content": user}]

    api = Api(p)
    paths = []
    n = args.n
    while True:
        notes = notes_text()
        print(f"generating {n} outline candidate(s) (max_parallel {p.cfg['max_parallel']})"
              + (f" with your notes:\n{notes}" if notes else " (no notes)") + "\n")
        res = api.chat_many("planner", make_msgs(notes), n)
        ts = stamp()
        new = []
        for text, _finish, _u in res:
            body, ok = extract_tagged(text, "outline")
            if not ok:
                warn("a candidate had no <outline> tags; check it for stray text")
            path = p.f("outlines", f"candidate_{ts}_{len(paths) + len(new) + 1}.md")
            write_text(path, (f"<!-- notes: {notes} -->\n" if notes else "") + body + "\n")
            new.append(path)
        if not new:
            warn("no candidates came back")
        else:
            first = len(paths) + 1
            paths += new
            page("\n\n".join(f"{'=' * 30} CANDIDATE {first + i} {'=' * 30}\n\n{read_text(pp)}" for i, pp in enumerate(new)))
        while True:
            for i, pp in enumerate(paths, 1):
                print(f"  [{i}] {pp}")
            c = ask("\nNUMBER save as outline.md / n [N] edit notes and re-roll / r [N] re-roll same notes / "
                    "v view all / Enter quit: ").strip().lower()
            if not c:
                return
            if c.isdigit() and 1 <= int(c) <= len(paths):
                if p.f("outline.md").exists():
                    shutil.copy2(p.f("outline.md"), p.f("outlines", f"outline_prev_{stamp()}.md"))
                body = re.sub(r"^<!-- notes:.*?-->\n", "", read_text(paths[int(c) - 1]), flags=re.S)
                write_text(p.f("outline.md"), body)
                print(f"wrote {p.f('outline.md')}")
                return
            if c == "v":
                page("\n\n".join(f"{'=' * 30} CANDIDATE {i} {'=' * 30}\n\n{read_text(pp)}" for i, pp in enumerate(paths, 1)))
                continue
            m = re.fullmatch(r"([nr])\s*(\d*)", c)
            if m:
                n = int(m.group(2)) if m.group(2) else args.n
                if m.group(1) == "n":
                    raw_notes = edit_saved(p, "outline_notes", raw_notes)
                break
            print("unknown choice")


def extract_json_array(text):
    t, _ok = extract_tagged(text, "scenes")
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip(), flags=re.M)
    a, b = t.find("["), t.rfind("]")
    if a < 0 or b <= a:
        return None
    try:
        v = json.loads(t[a: b + 1])
    except json.JSONDecodeError:
        return None
    return v if isinstance(v, list) else None


def cmd_scenes(p, args):
    outline = read_text(p.f("outline.md")).strip()
    if not outline:
        die(f"{p.f('outline.md')} is empty or missing (run: outline {p.root})")
    existing = p.scenes()
    if existing and not args.force:
        if any(s.get("status") != "planned" for s in existing) or any(p.f("trees").glob("*.json")):
            die("scenes are already being drafted; rerun with --force to replace scenes.json (trees are kept)")
    bible = read_text(p.f("bible.md")).strip()
    tw = int(p.cfg["target_words"])
    user = (
        f"# Story bible\n{bible}\n\n# Outline\n{outline}\n\n"
        "Break this outline into scene cards. A scene is one continuous stretch of time, place and POV.\n"
        "Return a JSON array, no prose, no code fence, between <scenes> and </scenes> tags (anything outside them is discarded). Each element:\n"
        '{"chapter": int, "title": str, "pov": str, "setting": str, "characters": [str], '
        '"goal": str, "conflict": str, "outcome": str, "beats": [str], "target_words": int}\n'
        "\"pov\" is the name of the POV character. \"characters\" lists every character physically present in the scene, "
        "by name, including the POV character; nobody else.\n"
        f"The target_words values must sum to about {tw}. Cover every beat of the outline, in order."
    )
    msgs = [{"role": "system", "content": PLANNER_SYSTEM}, {"role": "user", "content": user}]
    api = Api(p)
    while True:
        print("generating scene cards...")
        text, finish, _ = api.chat("planner", msgs)
        arr = extract_json_array(text)
        if arr is None or not all(isinstance(x, dict) for x in arr):
            warn(f"could not parse a JSON array (finish_reason={finish}); raw output saved")
            write_text(p.f("outlines", f"scenes_raw_{stamp()}.txt"), text)
            if ask("[r]egenerate / [q]uit: ").strip().lower().startswith("r"):
                continue
            return
        total = 0
        print(f"{'#':<4}{'ch':<4}{'words':<7}title")
        for k, s in enumerate(arr, 1):
            w = int(s.get("target_words") or 0)
            total += w
            print(f"{k:<4}{str(s.get('chapter', '?')):<4}{w:<7}{s.get('title', '')}")
        print(f"{len(arr)} scenes, {total} target words (project target {tw})")
        c = ask("[a]ccept / [v]iew all cards / [r]egenerate / [q]uit: ").strip().lower()
        if c.startswith("v"):
            page("\n\n".join(format_card(dict(s, id=f"#{k}")) for k, s in enumerate(arr, 1)))
            c = ask("[a]ccept / [r]egenerate / [q]uit: ").strip().lower()
        if c.startswith("r"):
            continue
        if not c.startswith("a"):
            return
        width = 3 if len(arr) > 99 else 2
        out = []
        for k, s in enumerate(arr, 1):
            out.append({
                "id": f"s{k:0{width}d}",
                "chapter": s.get("chapter", 1),
                "title": str(s.get("title", "")),
                "pov": str(s.get("pov", "")),
                "setting": str(s.get("setting", "")),
                "characters": [str(x) for x in s.get("characters", [])],
                "goal": str(s.get("goal", "")),
                "conflict": str(s.get("conflict", "")),
                "outcome": str(s.get("outcome", "")),
                "beats": [str(x) for x in s.get("beats", [])],
                "notes": "",
                "target_words": int(s.get("target_words") or 0),
                "status": "planned",
                "state_updated": False,
            })
        if existing:
            shutil.copy2(p.f("scenes.json"), p.f("outlines", f"scenes_prev_{stamp()}.json"))
        p.save_scenes(out)
        print(f"wrote {p.f('scenes.json')} (edit it by hand freely)")
        return


DRAFT_HELP = """generation:
  g [N]        generate N candidate passages (default: writer.swipes; N=1 streams live)
  s TEXT       set steering note (persists until changed); 's -' clears it
  l N          set target passage length in words for this session (also caps max_tokens)
scene cast:
  who A, B     set the characters physically present in this scene (saved to scenes.json)
  pov NAME     set the POV character ({{char}}) for this scene (saved to scenes.json)
lorebooks (files in lorebooks/; on/off and kinds saved to lorebooks.json):
  lb                   list lorebooks
  lb N [N ...]         toggle lorebook(s) on/off
  lb all on|off        switch every lorebook
  lb N char NAME       mark book N as a character lorebook for NAME
  lb N alias A, B      set other names that character goes by
  lb N world           mark book N as a world lorebook
editing and branches:
  w            write a passage yourself in $EDITOR (appended after head as a new paragraph)
  e            edit the head passage in place in $EDITOR
  r            rewind: move head back to its parent (branch is kept)
  t            show the branch tree
  j ID         jump head to node ID (switches branch)
  x ID         delete leaf node ID
  v            view scene text so far (with node markers)
  v ID         view one node's full text and metadata
  tail [N]     show the last N characters of the current scene (default 600)
info:
  card         show the scene card
  c            show context budget, samplers and injected lore for the next call
  cp           same, and dump the exact prompt to last_prompt.txt
  d            mark scene done and exit (then run update-state yourself)
  q            quit"""


def show_tree(tree):
    on_path = set(tree.chain()) if tree.head else set()

    def walk(parent, depth):
        for nid in tree.children(parent):
            n = tree.node(nid)
            mark = ">" if nid == tree.head else ("*" if nid in on_path else " ")
            preview = re.sub(r"\s+", " ", n["text"]).strip()[:70]
            src = n.get("source", "?")
            print(f"{'  ' * depth}{mark} {nid:<5} {words(n['text']):>4}w {src:<5} {preview}")
            walk(nid, depth + 1)

    print("(> head, * accepted path)")
    walk(None, 0)


def show_lorebooks(lore, sc):
    books = lore.books()
    if not books:
        print(f"no lorebooks in {lore.dir}")
        return
    present = sc.get("characters") or []
    pov = pov_name(sc)
    print(f"lorebooks ({lore.dir}):")
    for k, (fname, meta) in enumerate(books, 1):
        onoff = col("on ", "32") if meta.get("on") else col("off", "2")
        kind = meta.get("kind", "world")
        where = ""
        if kind == "character":
            name = lore.char_name(fname, meta)
            al = meta.get("aliases", [])
            if is_present(name, al, [pov]):
                where = "POV"
            elif is_present(name, al, present):
                where = "present"
            else:
                where = col("not in scene", "33")
            who = name + (f" ({', '.join(al)})" if al else "")
        else:
            who = ""
        n = len(lore.entries(fname))
        print(f"  {k:>2} [{onoff}] {kind:<9} {who:<28} {where:<14} {n:>4} entries  {fname}")


def lb_command(lore, sc, arg):
    books = lore.books()
    toks = arg.split()
    if not toks:
        show_lorebooks(lore, sc)
        return
    if toks[0] == "all" and len(toks) == 2 and toks[1] in ("on", "off"):
        for _, meta in books:
            meta["on"] = toks[1] == "on"
        lore.save()
        show_lorebooks(lore, sc)
        return
    if len(toks) >= 2 and toks[0].isdigit() and toks[1] in ("char", "alias", "world"):
        k = int(toks[0])
        if not 1 <= k <= len(books):
            print("no such lorebook number")
            return
        fname, meta = books[k - 1]
        rest = arg.split(None, 2)[2].strip() if len(arg.split(None, 2)) > 2 else ""
        if toks[1] == "world":
            meta["kind"] = "world"
        elif toks[1] == "char":
            if not rest:
                print("usage: lb N char NAME")
                return
            meta["kind"] = "character"
            meta["character"] = rest
        else:
            meta["aliases"] = [a.strip() for a in rest.split(",") if a.strip()]
        lore.save()
        show_lorebooks(lore, sc)
        return
    if all(t.isdigit() for t in toks):
        for t in toks:
            k = int(t)
            if 1 <= k <= len(books):
                books[k - 1][1]["on"] = not books[k - 1][1].get("on")
        lore.save()
        show_lorebooks(lore, sc)
        return
    print("lb usage: lb | lb N [N ...] | lb all on|off | lb N char NAME | lb N alias A, B | lb N world")


def node_flags(n):
    flags = []
    if n.get("ended"):
        flags.append("signals SCENE END")
    if n.get("trimmed"):
        flags.append("trimmed at length cutoff")
    if n.get("absent"):
        flags.append(col("mentions absent: " + ", ".join(n["absent"]), "33"))
    return flags


def node_header(nid, n):
    meta = [f"{words(n['text'])} words"]
    if n.get("source"):
        meta.append(str(n["source"]))
    if n.get("model"):
        meta.append(str(n["model"]))
    if n.get("parent"):
        meta.append(f"parent {n['parent']}")
    flags = node_flags(n)
    return f"{nid}  " + "  ".join(meta) + ("  " + "; ".join(flags) if flags else "")


def show_node(tree, nid):
    n = tree.node(nid)
    print(col(f"===== {node_header(nid, n)}", "36"))
    page(n["text"].strip())
    if n.get("steer"):
        print("steer used: " + n["steer"])


def show_candidate(tree, k, nid, with_text):
    n = tree.node(nid)
    flags = node_flags(n)
    print(col(f"\n===== [{k}] {nid}  {words(n['text'])} words", "36") + ("  " + "; ".join(flags) if flags else ""))
    if with_text:
        print(n["text"].strip())


PICK_HELP = ("K accept candidate K / r K [K ...] reroll those / r all reroll all / + N add N more / "
             "v K show candidate K again / d K delete / Enter keep all as branches")


def pick_candidates(p, tree, sc, scenes, cands, seen, gen):
    """cands: candidate node ids in display order. seen: ids whose text is already on screen (streamed live).
    gen(n) -> (new ids, ids streamed live). Rerolled candidates stay in the tree as branches."""
    shown = set()
    while True:
        if not cands:
            print("no candidates left")
            return False
        for k, nid in enumerate(cands, 1):
            if nid not in shown:
                show_candidate(tree, k, nid, with_text=nid not in seen)
                shown.add(nid)
        c = ask(f"\n{PICK_HELP}\n> ").strip().lower()
        if not c:
            return False
        m_acc = re.fullmatch(r"\d+", c)
        m_rr = re.fullmatch(r"r\s+(all|[\d\s,]+)", c)
        m_add = re.fullmatch(r"\+\s*(\d*)", c)
        m_view = re.fullmatch(r"v\s*(\d+)", c)
        m_del = re.fullmatch(r"d\s*(\d+)", c)
        if m_acc and 1 <= int(c) <= len(cands):
            nid = cands[int(c) - 1]
            tree.head = nid
            tree.save()
            if sc["status"] == "planned":
                sc["status"] = "drafting"
                p.save_scenes(scenes)
            print(f"accepted {nid}")
            if tree.node(nid).get("ended"):
                if ask("the model signalled scene end. mark scene done? [y/N] ").strip().lower() == "y":
                    return "done"
            return True
        if m_rr:
            if m_rr.group(1) == "all":
                ks = list(range(1, len(cands) + 1))
            else:
                ks = sorted({int(x) for x in re.findall(r"\d+", m_rr.group(1)) if 1 <= int(x) <= len(cands)})
            if not ks:
                print("no such candidate")
                continue
            new, streamed = gen(len(ks))
            seen |= set(streamed)
            for k, nid in zip(ks, new):
                print(f"[{k}] {cands[k - 1]} rerolled -> {nid} (old text kept as a branch)")
                cands[k - 1] = nid
            if len(new) < len(ks):
                warn(f"only {len(new)} of {len(ks)} rerolls came back; the rest keep their old text")
            continue
        if m_add:
            new, streamed = gen(max(1, int(m_add.group(1) or 1)))
            seen |= set(streamed)
            cands.extend(new)
            continue
        if m_view and 1 <= int(m_view.group(1)) <= len(cands):
            show_candidate(tree, int(m_view.group(1)), cands[int(m_view.group(1)) - 1], with_text=True)
            continue
        if m_del and 1 <= int(m_del.group(1)) <= len(cands):
            nid = cands[int(m_del.group(1)) - 1]
            if tree.delete(nid):
                tree.save()
                cands.remove(nid)
                shown.clear()
                print(f"deleted {nid}")
            continue
        print("unknown choice")


def cmd_draft(p, args):
    scenes = p.scenes()
    if not scenes:
        die(f"no scenes (run: scenes {p.root})")
    preset = p.preset()
    rc = p.cfg["roles"]["writer"]
    stale = [k for k in SAMPLING_KEYS if k in rc]
    if stale:
        warn("writer keys " + ", ".join(stale) + " in project.json are ignored: writer samplers come from the preset")
    if args.scene:
        idx = p.scene_index(scenes, args.scene)
    else:
        idx = next((i for i, s in enumerate(scenes) if s.get("status") != "done"), None)
        if idx is None:
            die("all scenes are done (use --scene ID to reopen one)")
    sc = scenes[idx]
    sums = p.summaries()["scenes"]
    for s in scenes[:idx]:
        if s.get("status") != "done":
            warn(f"earlier scene {s['id']} is not marked done")
        elif s["id"] not in sums:
            warn(f"earlier scene {s['id']} has no summary/state update (run: update-state {p.root} --scene {s['id']})")
    tree = Tree(p, sc["id"])
    lore = Lore(p, scenes)
    passage_words = int(rc.get("passage_words", 220))
    steer = tree.d.get("steer", "")
    if steer:
        print(f"restored steering note: {steer}")
    api = None
    _prompt, _params, _extra, ignored, _rep = build_writer_prompt(p, preset, lore, scenes, idx, tree, steer, passage_words)
    print(f"writer preset: {preset['preset'].get('name', p.preset_path().name)}  temp {preset['preset'].get('temp')}")
    if ignored:
        warn("preset samplers with no Featherless parameter (not sent): " + ", ".join(ignored))
    if preset["preset"].get("temperature_last"):
        warn("preset has temperature_last; Featherless doesn't expose sampler order, so the server's default order applies")
    print(col(format_card(sc), "36"))
    show_lorebooks(lore, sc)
    if tree.head:
        n = tree.node(tree.head)
        print(col(f"resume {node_header(tree.head, n)}", "36"))
        print("  ends: " + tail_trim_chars(500, n["text"], marker="…").replace("\n", "\n  "))
        if n.get("steer"):
            print("  steer used: " + n["steer"])
        siblings = [x for x in tree.children(n.get("parent")) if x != tree.head]
        if siblings:
            more = ", ".join(siblings[:8]) + (", ..." if len(siblings) > 8 else "")
            print(f"  {len(siblings)} other branch(es): {more}  (v ID to read one)")
    print("type ? for commands")
    while True:
        sw = words(tree.text()) if tree.head else 0
        sib = len(tree.children(tree.node(tree.head)["parent"])) if tree.head else 0
        status = (f"[{sc['id']} {sw}/{sc.get('target_words', '?')}w head={tree.head or '-'} siblings={sib} "
                  f"len={passage_words}w pov={pov_name(sc)} lore={len(lore.active())} on]")
        if steer:
            status += col(f" steer: {steer[:60]}", "35")
        raw = ask(col(status, "2") + "\ndraft> ").strip()
        if not raw:
            continue
        cmd, _, arg = raw.partition(" ")
        cmd = cmd.lower()
        arg = arg.strip()
        try:
            if cmd in ("?", "h", "help"):
                print(DRAFT_HELP)
            elif cmd == "q":
                return
            elif cmd == "card":
                print(format_card(sc))
            elif cmd == "s":
                steer = "" if arg in ("", "-") else arg
                tree.d["steer"] = steer
                tree.save()
                print("steer cleared" if not steer else "steer set")
            elif cmd == "l":
                if arg.isdigit() and int(arg) > 0:
                    passage_words = int(arg)
            elif cmd == "who":
                names = [x.strip() for x in arg.split(",") if x.strip()]
                if names:
                    sc["characters"] = names
                    p.save_scenes(scenes)
                print("present: " + (", ".join(sc.get("characters") or []) or "(none)"))
            elif cmd == "pov":
                if arg:
                    sc["pov"] = arg
                    p.save_scenes(scenes)
                print(f"pov: {sc.get('pov', '')}  -> {{{{char}}}} = {pov_name(sc)}")
            elif cmd == "lb":
                lore.sync(scenes)
                lb_command(lore, sc, arg)
            elif cmd in ("c", "cp"):
                prompt, params, extra, _ig, rep = build_writer_prompt(p, preset, lore, scenes, idx, tree, steer, passage_words)
                print_report(rep, params, extra)
                if cmd == "cp":
                    write_text(p.f("last_prompt.txt"), prompt)
                    print(f"wrote {p.f('last_prompt.txt')}")
            elif cmd == "g" or re.fullmatch(r"g\d+", cmd):
                n = int(cmd[1:]) if len(cmd) > 1 else (int(arg) if arg.isdigit() else int(rc.get("swipes", 1)))
                n = max(1, n)
                head_at_start = tree.head

                def gen(count, _head=head_at_start):
                    """Generate count candidates after _head. One streams live; several run per max_parallel."""
                    nonlocal api
                    prompt, params, extra, _ig, rep = build_writer_prompt(p, preset, lore, scenes, idx, tree, steer, passage_words)
                    for note in rep["notes"]:
                        warn(note)
                    if rep["over"]:
                        print_report(rep, params, extra)
                        return [], []
                    api = api or Api(p)
                    meta = {"scene": sc["id"], "head": _head, "lorebooks": lore.active(),
                            "present": sc.get("characters") or [], "char": rep["char"], "steer": steer}
                    try:
                        if count == 1:
                            print(col("--- streaming ---", "2"))
                            text, finish, _ = api.complete("writer", prompt, params, extra,
                                                           stream_cb=lambda t: print(t, end="", flush=True), meta=meta)
                            print()
                            results, live = [(text, finish, None)], True
                        else:
                            print(f"generating {count} candidates (max_parallel {p.cfg['max_parallel']})...")
                            results = api.many(lambda: api.complete("writer", prompt, params, extra, meta=meta), count)
                            live = False
                    except (HttpErr, NoAnswerErr, httpx.HTTPError) as e:
                        print(col(f"generation failed: {e}", "31"))
                        return [], []
                    ids = []
                    for text, finish, _ in results:
                        clean, ended, trimmed = clean_continuation(text, finish, rep["continuing"])
                        if not clean.strip():
                            continue
                        ids.append(tree.add(
                            _head, clean, source="model", sep="" if rep["continuing"] else "\n\n", model=rc["model"],
                            steer=steer, ended=ended, trimmed=trimmed, finish=finish, lorebooks=lore.active(),
                            present=sc.get("characters") or [], absent=lore.absent_mentions(sc, clean)))
                    tree.save()
                    return ids, (ids if live else [])

                cands, streamed = gen(n)
                if pick_candidates(p, tree, sc, scenes, cands, set(streamed), gen) == "done":
                    sc["status"] = "done"
                    p.save_scenes(scenes)
                    print(f"scene {sc['id']} done. next step: update-state {p.root} --scene {sc['id']}")
                    return
            elif cmd == "w":
                txt = edit_saved(p, f"passage_{sc['id']}", "").strip()
                if txt:
                    tree.head = tree.add(tree.head, txt, source="user", sep="\n\n")
                    tree.save()
                    if sc["status"] == "planned":
                        sc["status"] = "drafting"
                        p.save_scenes(scenes)
                    print(f"added {tree.head}")
            elif cmd == "e":
                if not tree.head:
                    print("nothing to edit")
                    continue
                n = tree.node(tree.head)
                new = edit_saved(p, f"edit_{sc['id']}_{tree.head}", n["text"]).rstrip()
                if n.get("sep") == "":
                    new = keep_lead(n["text"], new)
                if new.strip() and new != n["text"]:
                    n["history"].append({"time": now(), "text": n["text"], "by": "user-edit"})
                    n["text"] = new
                    tree.save()
                    print(word_diff(n["history"][-1]["text"], new))
            elif cmd == "r":
                if tree.head:
                    tree.head = tree.node(tree.head)["parent"]
                    tree.save()
                    print(f"head -> {tree.head or '(scene start)'}")
            elif cmd == "t":
                show_tree(tree)
            elif cmd == "j":
                if arg in tree.d["nodes"]:
                    tree.head = arg
                    tree.save()
                    print(f"head -> {arg}")
                else:
                    print("no such node")
            elif cmd == "x":
                if arg in tree.d["nodes"]:
                    print("deleted" if tree.delete(arg) else "node has children; not deleted")
                    tree.save()
            elif cmd == "v":
                if arg:
                    if arg in tree.d["nodes"]:
                        show_node(tree, arg)
                    else:
                        print("no such node")
                elif tree.head:
                    page("\n\n".join(f"--- {i} ---\n{tree.node(i)['text'].strip()}" for i in tree.chain()))
                else:
                    print("(empty)")
            elif cmd == "tail":
                if not tree.head:
                    print("(empty)")
                else:
                    n = int(arg) if arg.isdigit() and int(arg) > 0 else 600
                    print(col(f"last {n} chars (head {tree.head}):", "36"))
                    print(tail_trim_chars(n, tree.text(), marker="…"))
            elif cmd == "d":
                sc["status"] = "done"
                p.save_scenes(scenes)
                print(f"scene {sc['id']} done. next step: update-state {p.root} --scene {sc['id']}")
                return
            else:
                print("unknown command; ? for help")
        except KeyboardInterrupt:
            print("\ninterrupted")
        except HttpErr as e:
            print(col(str(e), "31"))


def cmd_update_state(p, args):
    scenes = p.scenes()
    sums = p.summaries()
    if args.scene:
        idx = p.scene_index(scenes, args.scene)
    else:
        idx = next((i for i, s in enumerate(scenes) if s.get("status") == "done" and not s.get("state_updated")), None)
        if idx is None:
            die("no done scene is waiting for a state update (use --scene ID)")
    sc = scenes[idx]
    tree = Tree(p, sc["id"])
    if not tree.head:
        die(f"scene {sc['id']} has no text")
    if sc.get("status") != "done":
        warn(f"scene {sc['id']} is not marked done")
    later = [s["id"] for s in scenes[idx + 1:] if s.get("state_updated")]
    summary_only = args.summary_only
    if later and not summary_only:
        warn("state.md already includes later scenes (" + ", ".join(later) + "); "
             "updating state from this scene would treat that as 'before'. Use --summary-only to refresh summaries only.")
        if ask("continue anyway? [y/N] ").strip().lower() != "y":
            return
    scene_text = tree.text()
    bible = read_text(p.f("bible.md")).strip()
    state = read_text(p.f("state.md")).strip()
    cfg = p.cfg["summary"]
    model = p.cfg["roles"]["summarizer"]["model"]
    names = ["DETAILED SUMMARY", "BRIEF SUMMARY"] + ([] if summary_only else ["UPDATED STATE"])
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
    instr += "Put all the sections between <record> and </record> tags, with nothing else inside them. Anything outside the tags is discarded."
    user = (f"# Story bible\n{bible}\n\n# Scene card\n{format_card(sc)}\n\n"
            + ("" if summary_only else f"# Continuity state BEFORE this scene\n{state}\n\n")
            + f"# Full text of the scene\n{scene_text}\n\n{instr}")
    msgs = [{"role": "system", "content": SUMMARIZER_SYSTEM}, {"role": "user", "content": user}]
    ceil, _, src = p.ceiling(model)
    need = p.est(model, SUMMARIZER_SYSTEM + user) + int(p.cfg["roles"]["summarizer"]["max_tokens"])
    if need > ceil:
        warn(f"request needs ~{need} tokens but ceiling is {ceil} ({src}); the call may fail")
    api = Api(p)
    while True:
        print(f"summarizing {sc['id']}...")
        text, finish, _ = api.chat("summarizer", msgs)
        secs = parse_sections(extract_tagged(text, "record")[0], names)
        while True:
            if secs is None:
                warn(f"could not find all sections (finish_reason={finish})")
                print(text)
                c = ask("[e]dit raw / [r]egenerate / [q]uit: ").strip().lower()
                if c.startswith("e"):
                    text = edit_saved(p, f"state_raw_{sc['id']}", text)
                    secs = parse_sections(text, names)
                    continue
                if c.startswith("r"):
                    break
                return
            print(col("\n=== DETAILED SUMMARY ===", "36"))
            print(secs["DETAILED SUMMARY"])
            print(col("\n=== BRIEF SUMMARY ===", "36"))
            print(secs["BRIEF SUMMARY"])
            if not summary_only:
                print(col("\n=== STATE DIFF ===", "36"))
                print(line_diff(state, secs["UPDATED STATE"], "state.md", "updated"))
            c = ask("\n[a]ccept / [e]dit / [r]egenerate / [q]uit: ").strip().lower()
            if c.startswith("e"):
                blob = "\n\n".join(f"=== {n} ===\n{secs[n]}" for n in names)
                text = edit_saved(p, f"state_edit_{sc['id']}", blob)
                secs = parse_sections(text, names)
                continue
            if c.startswith("r"):
                break
            if not c.startswith("a"):
                return
            if not summary_only:
                shutil.copy2(p.f("state.md"), p.f("state_history", f"before_{sc['id']}_{stamp()}.md"))
                write_text(p.f("state.md"), secs["UPDATED STATE"].strip() + "\n")
                sc["state_updated"] = True
            sums["scenes"][sc["id"]] = {
                "detailed": secs["DETAILED SUMMARY"], "brief": secs["BRIEF SUMMARY"],
                "updated": now(), "text_hash": text_hash(scene_text),
            }
            p.save_summaries(sums)
            p.save_scenes(scenes)
            print("saved summaries" + ("" if summary_only else " and state.md"))
            return


def cmd_compress(p, args):
    scenes = p.scenes()
    lo, hi = p.scene_index(scenes, args.from_id), p.scene_index(scenes, args.to_id)
    if hi < lo:
        die("--to must not come before --from")
    sums = p.summaries()
    pos = {s["id"]: i for i, s in enumerate(scenes)}
    for a in sums.get("arcs", []):
        if a["from"] in pos and a["to"] in pos and not (pos[a["to"]] < lo or pos[a["from"]] > hi):
            if not args.replace:
                die(f"overlaps existing arc {a['from']}-{a['to']} (use --replace)")
    rng = scenes[lo: hi + 1]
    missing = [s["id"] for s in rng if s["id"] not in sums["scenes"]]
    if missing:
        die("no summaries for: " + ", ".join(missing))
    body = "\n\n".join(f"### {s['id']}: {s.get('title', '')}\n{sums['scenes'][s['id']]['detailed']}" for s in rng)
    aw = p.cfg["summary"]["arc_words"]
    user = (f"# Scene summaries {rng[0]['id']}-{rng[-1]['id']}\n{body}\n\n"
            f"Condense these into one continuous summary of about {aw} words. Keep every fact later scenes may depend on: "
            "who knows what, promises and setups, injuries, objects, relationship changes, unresolved threads. " + tag_instr("summary"))
    msgs = [{"role": "system", "content": SUMMARIZER_SYSTEM}, {"role": "user", "content": user}]
    api = Api(p)
    while True:
        raw, _, _ = api.chat("summarizer", msgs)
        text, ok = extract_tagged(raw, "summary")
        if not ok:
            warn("no <summary> tags in the output; check it for stray text")
        print(text)
        c = ask(f"\n({words(text)} words) [a]ccept / [e]dit / [r]egenerate / [q]uit: ").strip().lower()
        if c.startswith("e"):
            text = edit_saved(p, f"arc_{rng[0]['id']}_{rng[-1]['id']}", text).strip()
            c = "a"
        if c.startswith("r"):
            continue
        if not c.startswith("a"):
            return
        arcs = [a for a in sums.get("arcs", [])
                if not (a["from"] in pos and a["to"] in pos and not (pos[a["to"]] < lo or pos[a["from"]] > hi))]
        arcs.append({"from": rng[0]["id"], "to": rng[-1]["id"], "text": text, "updated": now()})
        sums["arcs"] = arcs
        p.save_summaries(sums)
        print(f"saved arc {rng[0]['id']}-{rng[-1]['id']}")
        return


def cmd_critique(p, args):
    scenes = p.scenes()
    idx = p.scene_index(scenes, args.scene)
    sc = scenes[idx]
    tree = Tree(p, sc["id"])
    if not tree.head:
        die(f"scene {sc['id']} has no text")
    model = p.cfg["roles"]["critic"]["model"]
    summary, notes = layered_summary(p, scenes, idx, int(p.cfg["budget_tokens"]["summary"]), model)
    for n in notes:
        warn(n)
    banned = ", ".join(f'"{b}"' for b in p.cfg["banned_phrases"])
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
        "After the list, one line: 'Scene card fulfilled: yes/partly/no - reason'. " + tag_instr("critique")
    )
    msgs = [{"role": "system", "content": CRITIC_SYSTEM}, {"role": "user", "content": user}]
    print(f"critiquing {sc['id']}...")
    raw, _, _ = Api(p).chat("critic", msgs)
    text, ok = extract_tagged(raw, "critique")
    if not ok:
        warn("no <critique> tags in the output; check it for stray text")
    out = p.f("critiques", f"{sc['id']}.md")
    if out.exists():
        shutil.copy2(out, p.f("critiques", f"{sc['id']}_prev_{stamp()}.md"))
    write_text(out, f"# Critique {sc['id']} ({now()})\n\n{text}\n")
    page(text)
    print(f"wrote {out} (edit it to drop points you disagree with before running revise)")

def cmd_check(p, args):
    scenes = p.scenes()
    targets = [scenes[p.scene_index(scenes, args.scene)]] if args.scene else scenes
    banned = [b for b in p.cfg["banned_phrases"] if b.strip()]
    ng = p.cfg["ngram"]
    n, min_count, top = int(ng["n"]), int(ng["min_count"]), int(ng["top"])
    scene_texts = []
    for s in targets:
        tree = Tree(p, s["id"])
        if not tree.head:
            continue
        scene_texts.append((s["id"], [(nid, tree.node(nid)["text"]) for nid in tree.chain()], tree.text()))
    title = f"# Check {'scene ' + args.scene if args.scene else 'all scenes'} ({now()})"
    report = check_report(scene_texts, banned, n, min_count, top, title)
    out = p.f("checks", f"{args.scene or 'all'}.md")
    write_text(out, report)
    print(report)
    print(f"wrote {out}")


def cmd_revise(p, args):
    scenes = p.scenes()
    idx = p.scene_index(scenes, args.scene)
    sc = scenes[idx]
    tree = Tree(p, sc["id"])
    if not tree.head:
        die(f"scene {sc['id']} has no text")
    notes = []
    for path in (p.f("critiques", f"{sc['id']}.md"), p.f("checks", f"{sc['id']}.md")):
        if path.exists():
            notes.append(read_text(path).strip())
    if not notes:
        die(f"no notes for {sc['id']}: run critique {p.root} --scene {sc['id']} and/or check {p.root} --scene {sc['id']} first")
    notes_text = "\n\n".join(notes)
    bible = read_text(p.f("bible.md")).strip()
    api = Api(p)
    chain = tree.chain()
    changed = 0
    for k, nid in enumerate(chain):
        n = tree.node(nid)
        prev_tail = tree.text(chain[k - 1])[-900:] if k > 0 else ""
        cast = ", ".join(sc.get("characters") or [])
        user = (
            f"# Story bible (style rules apply)\n{bible}\n\n"
            + (f"# Characters present in this scene\n{cast}\n\n" if cast else "")
            + f"# Editor's notes for this scene\n{notes_text}\n\n"
            + (f"# Text just before the passage (context only, do not output it)\n...{prev_tail}\n\n" if prev_tail else "")
            + f"# Passage to revise\n{n['text'].strip()}\n\n"
            "Fix only the listed problems that occur in this passage. If none occur in it, answer NO CHANGES. "
            "Otherwise answer with the full revised passage. " + tag_instr("passage")
        )
        msgs = [{"role": "system", "content": EDITOR_SYSTEM}, {"role": "user", "content": user}]
        while True:
            print(col(f"\n--- {nid} ({k + 1}/{len(chain)}) ---", "36"))
            text, finish, _ = api.chat("editor", msgs, max_tokens=max(int(p.cfg["roles"]["editor"]["max_tokens"]), int(words(n["text"]) * 2)))
            text, ok = extract_tagged(text, "passage")
            if not ok and not text.upper().startswith("NO CHANGES"):
                warn("no <passage> tags in the editor output; check it for stray text")
            if text.upper().startswith("NO CHANGES") or text == n["text"].strip():
                print("no changes")
                break
            if finish == "length":
                warn("editor output hit max_tokens; it may be truncated")
            print(word_diff(n["text"].strip(), text))
            c = ask(f"\n({words(n['text'])} -> {words(text)} words) [a]ccept / [s]kip / [e]dit / [r]egenerate / [q]uit: ").strip().lower()
            if c.startswith("e"):
                text = edit_saved(p, f"revise_{sc['id']}_{nid}", text).strip()
                c = "a"
            if c.startswith("r"):
                continue
            if c.startswith("a") and text:
                if n.get("sep") == "":
                    text = keep_lead(n["text"], text)
                n["history"].append({"time": now(), "text": n["text"], "by": "revise"})
                n["text"] = text
                tree.save()
                changed += 1
            if c.startswith("q"):
                print(f"revised {changed} passages")
                return
            break
    print(f"revised {changed} passages")
    rec = p.summaries()["scenes"].get(sc["id"])
    if changed and rec:
        warn(f"summary for {sc['id']} is now stale (run: update-state {p.root} --scene {sc['id']} --summary-only)")


def cmd_status(p, args):
    scenes = p.scenes()
    sums = p.summaries()["scenes"]
    print(f"{p.cfg['title']}  ({p.root})")
    for role, rc in p.cfg["roles"].items():
        if role == "writer" and p.preset_path().exists():
            pr = p.preset()
            ceil, _, src = p.writer_ceiling(pr)
            extra = f"  preset {pr['preset'].get('name', p.preset_path().name)} temp {pr['preset'].get('temp')}"
        else:
            ceil, _, src = p.ceiling(rc["model"])
            extra = "  (preset missing: " + str(p.preset_path()) + ")" if role == "writer" else ""
        print(f"  {role:<10} {rc['model']}  ceiling {ceil} ({src}){extra}")
    lore = Lore(p, scenes)
    act = lore.active()
    print(f"  lorebooks on: {', '.join(act) if act else '(none)'}")
    print(f"\n{'id':<6}{'ch':<4}{'status':<10}{'words':>12}  {'summary':<8}{'crit':<5}title")
    total = 0
    for s in scenes:
        tree = Tree(p, s["id"])
        txt = tree.text() if tree.head else ""
        w = words(txt)
        total += w
        rec = sums.get(s["id"])
        summ = "-" if not rec else ("stale" if rec.get("text_hash") != text_hash(txt) else "ok")
        crit = "yes" if p.f("critiques", f"{s['id']}.md").exists() else "-"
        print(f"{s['id']:<6}{str(s.get('chapter', '?')):<4}{s.get('status', '?'):<10}{w:>6}/{s.get('target_words', 0):<5}  {summ:<8}{crit:<5}{s.get('title', '')}")
    print(f"\ntotal {total} / {p.cfg['target_words']} words; arcs: {len(p.summaries().get('arcs', []))}")


def cmd_export(p, args):
    scenes = p.scenes()
    out_path = Path(args.out).expanduser().resolve() if args.out else p.f("manuscript.md")
    parts = [f"# {p.cfg['title']}"]
    last_ch = None
    total = 0
    for s in scenes:
        tree = Tree(p, s["id"])
        if not tree.head:
            continue
        txt = tree.text()
        total += words(txt)
        ch = s.get("chapter")
        if ch != last_ch:
            parts.append(f"## Chapter {ch}")
            last_ch = ch
        elif len(parts) > 1 and not parts[-1].startswith("## "):
            parts.append("* * *")
        parts.append(txt)
    write_text(out_path, "\n\n".join(parts) + "\n")
    print(f"wrote {out_path} ({total} words)")

