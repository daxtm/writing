"""Writer prompt assembly and context reports."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .config import ST_UNSENDABLE
from .lore import assemble_lore, pov_name
from .tree import Tree
from .utils import col, read_text, warn, words

def format_card(s):
    lines = [f"Scene {s['id']} (Chapter {s.get('chapter', '?')}): {s.get('title', '')}"]
    for key, label in (("pov", "POV"), ("setting", "Setting")):
        if s.get(key):
            lines.append(f"{label}: {s[key]}")
    if s.get("characters"):
        lines.append("Characters present: " + ", ".join(s["characters"]))
    for key, label in (("goal", "Goal"), ("conflict", "Conflict"), ("outcome", "Outcome (where the scene must end up)")):
        if s.get(key):
            lines.append(f"{label}: {s[key]}")
    if s.get("beats"):
        lines.append("Beats:")
        lines += [f"- {b}" for b in s["beats"]]
    if s.get("notes"):
        lines.append(f"Notes: {s['notes']}")
    if s.get("target_words"):
        lines.append(f"Target length: ~{s['target_words']} words")
    return "\n".join(lines)


def tail_trim_chars(chars, text, marker="..."):
    """Trim `text` to its last `chars` characters at a clean boundary (pure)."""
    if len(text) <= chars:
        return text
    cut = text[-chars:]
    para = cut.find("\n\n")
    if 0 <= para < len(cut) * 0.4:
        return (marker + "\n" if marker else "") + cut[para:].lstrip("\n")
    m = re.search(r"[.!?…][\"'”’)*]*\s+", cut)
    if m and m.end() < len(cut) * 0.4:
        return marker + cut[m.end():]
    return marker + cut


def tail_trim(p, model, text, budget, marker="..."):
    return tail_trim_chars(int(budget * p.ratio(model)), text, marker)


def layered_summary_core(sums, cfg, scenes, idx, budget, est, model, root):
    """Pure selection/rendering of layered scene summaries; returns (text, notes).

    `sums` is the loaded summaries.json content, `cfg` the summary config, `est`
    a (model, text) -> int token estimator, `root` the project root shown in notes.
    """
    notes = []
    pos = {s["id"]: i for i, s in enumerate(scenes)}
    arcs = []
    for a in sums.get("arcs", []):
        if a.get("from") in pos and a.get("to") in pos:
            lo, hi = pos[a["from"]], pos[a["to"]]
            if lo <= hi < idx:
                arcs.append((lo, hi, a["text"]))
    arcs.sort()
    arc_at = {lo: (hi, txt) for lo, hi, txt in arcs}
    entries = []
    j = 0
    while j < idx:
        if j in arc_at:
            hi, txt = arc_at[j]
            entries.append({"kind": "arc", "label": f"Scenes {scenes[j]['id']}-{scenes[hi]['id']}", "detailed": txt, "brief": txt})
            j = hi + 1
            continue
        s = scenes[j]
        rec = sums["scenes"].get(s["id"])
        label = f"{s['id']} - Ch {s.get('chapter', '?')}: {s.get('title', '')}"
        if rec:
            entries.append({"kind": "scene", "label": label, "detailed": rec["detailed"], "brief": rec["brief"]})
        else:
            entries.append({"kind": "missing", "label": label, "detailed": "", "brief": ""})
            notes.append(f"{s['id']} has no summary (run: update-state {root} --scene {s['id']})")
        j += 1
    if not entries:
        return "", notes
    scene_pos = [k for k, e in enumerate(entries) if e["kind"] == "scene"]
    kd = int(cfg["detailed_recent_scenes"])
    detailed = set(scene_pos[-kd:]) if kd > 0 else set()

    def render(entries_, detailed_, dropped):
        out = []
        if dropped:
            out.append(f"[{dropped} earlier summary entries omitted for space]")
        for k, e in entries_:
            if e["kind"] == "missing":
                out.append(f"### {e['label']}\n[no summary recorded]")
            else:
                out.append(f"### {e['label']}\n" + (e["detailed"] if k in detailed_ else e["brief"]))
        return "\n\n".join(out)

    indexed = list(enumerate(entries))
    dropped = 0
    text = render(indexed, detailed, dropped)
    order = sorted(detailed)
    while est(model, text) > budget and order:
        detailed.discard(order.pop(0))
        text = render(indexed, detailed, dropped)
    while est(model, text) > budget and len(indexed) > 1:
        indexed.pop(0)
        dropped += 1
        text = render(indexed, detailed, dropped)
    if dropped:
        notes.append(f"summary over budget: {dropped} oldest entries dropped (run: compress)")
    return text, notes


def layered_summary(p, scenes, idx, budget, model):
    sums = p.summaries()
    cfg = p.cfg["summary"]
    return layered_summary_core(sums, cfg, scenes, idx, budget, p.est, model, p.root)


def render_story_string(tpl, fields):
    def if_block(m):
        return m.group(2) if fields.get(m.group(1)) else ""
    s = re.sub(r"\{\{#if (\w+)\}\}(.*?)\{\{/if\}\}", if_block, tpl, flags=re.S)
    s = re.sub(r"\{\{(\w+)\}\}", lambda m: m.group(0) if m.group(1) == "trim" else str(fields.get(m.group(1), "")), s)
    return re.sub(r"\n*\{\{trim\}\}\n*", "", s)


def writer_sampling(preset, mac):
    s = preset["preset"]
    params = {"temperature": float(s.get("temp", 1.0))}
    for src, dst in (("top_p", "top_p"), ("min_p", "min_p"), ("rep_pen", "repetition_penalty"),
                     ("freq_pen", "frequency_penalty"), ("presence_pen", "presence_penalty")):
        if s.get(src) is not None:
            params[dst] = float(s[src])
    if int(s.get("top_k", 0) or 0) > 0:
        params["top_k"] = int(s["top_k"])
    if s.get("genamt"):
        params["max_tokens"] = int(s["genamt"])
    stop = preset["instruct"].get("stop_sequence")
    if stop:
        params["stop"] = [mac(stop)]
    extra = {}
    if float(s.get("dry_multiplier", 0) or 0) > 0:
        br = s.get("dry_sequence_breakers", "[]")
        try:
            br = json.loads(mac(br)) if isinstance(br, str) else [mac(x) for x in br]
        except json.JSONDecodeError:
            br = []
        extra = {"dry_multiplier": float(s["dry_multiplier"]), "dry_base": float(s.get("dry_base", 1.75)),
                 "dry_allowed_length": int(s.get("dry_allowed_length", 2)), "dry_sequence_breakers": br}
        if int(s.get("dry_penalty_last_n", 0) or 0) > 0:
            extra["dry_penalty_last_n"] = int(s["dry_penalty_last_n"])
    ignored = [k for k, active in ST_UNSENDABLE if k in s and active(s[k])]
    if s.get("rep_pen_range") and float(s.get("rep_pen", 1) or 1) != 1:
        ignored.append("rep_pen_range")
    return params, extra, ignored


@dataclass
class PromptInputs:
    """Loaded and derived values for the pure writer-prompt composition.

    Named fields keep the call site readable; the object carries no file,
    project, or network handles.
    """

    rb: int
    sb: int
    scenes: list
    idx: int
    ins: dict
    story_string: str
    mac: object
    char: str
    user: str
    bible: str
    state: str
    card: str
    scene_text: str
    continuing: bool
    prev_src: str
    steer: str
    passage_words: int
    lfields: dict
    cast: str
    progress: str
    system: str
    out_seq: str
    sums: dict
    summary_cfg: dict
    est: object
    ratio: object
    model: str
    root: Path | str


def compose_writer_prompt(inp):
    """Pure writer prompt composition from already-loaded strings and objects.

    Returns the exact (prompt, parts, summary_notes) for the given recent and
    summary budgets; no file, project, or network access.
    """
    rb, sb = inp.rb, inp.sb
    summary, snotes = layered_summary_core(
        inp.sums, inp.summary_cfg, inp.scenes, inp.idx, sb, inp.est, inp.model, inp.root)
    scenario = inp.bible
    if summary:
        scenario += "\n\nStory so far:\n" + summary
    scenario += "\n\nContinuity state:\n" + (inp.state or "(none yet)")
    fields = {
        "system": inp.system, "wiBefore": inp.mac(inp.lfields["wiBefore"]),
        "description": inp.mac(inp.lfields["description"]),
        "personality": "", "persona": "", "scenario": inp.mac(scenario),
        "wiAfter": inp.mac(inp.lfields["wiAfter"]),
        "mesExamples": "", "char": inp.char, "user": inp.user,
    }
    story = render_story_string(inp.story_string, fields)
    a = [inp.card]
    if inp.cast:
        a.append(inp.cast)
    a.append(inp.progress)
    if not inp.continuing and inp.prev_src:
        a.append("End of the previous scene (context only; this scene begins now):\n"
                 + tail_trim_chars(int(rb * inp.ratio(inp.model)), inp.prev_src))
    if not inp.continuing and inp.idx == 0:
        a.append("This is the opening of the story.")
    if inp.steer:
        a.append("Direction for this passage: " + inp.steer)
    a.append(
        f"Write this scene as prose from {inp.char}'s point of view, following the POV, tense and style rules in the scenario. "
        + ("Continue from exactly where the text leaves off" if inp.continuing else "Begin the scene")
        + f", about {inp.passage_words} words. Never repeat what is already written. Stay inside this scene. "
        "When the scene's outcome has been reached, finish at a natural stopping point and write [SCENE END] on its own line."
    )
    author = inp.mac("\n\n".join(a))
    prefill = tail_trim_chars(int(rb * inp.ratio(inp.model)), inp.scene_text, marker="") if inp.continuing else ""
    prompt = (story + inp.mac(inp.ins.get("input_sequence", ""), inp.user) + author
              + inp.ins.get("input_suffix", "") + inp.mac(inp.out_seq, inp.char) + prefill)
    parts = {
        "sysprompt": inp.est(inp.model, inp.system), "bible": inp.est(inp.model, inp.bible),
        "summary": inp.est(inp.model, summary), "state": inp.est(inp.model, inp.state),
        "lore": inp.est(inp.model, inp.lfields["wiBefore"] + inp.lfields["description"] + inp.lfields["wiAfter"]),
        "author_turn": inp.est(inp.model, author), "prefill": inp.est(inp.model, prefill),
    }
    return prompt, parts, snotes


def build_writer_prompt(p, preset, lore, scenes, idx, tree, steer, passage_words):
    rc = p.cfg["roles"]["writer"]
    model = rc["model"]
    B = p.cfg["budget_tokens"]
    sc = scenes[idx]
    notes = []
    user = rc.get("user_name", "Author")
    char = pov_name(sc)
    ins = preset["instruct"]
    use_macro = ins.get("macro", True)

    def mac(s, name=None):
        s = (s or "").replace("{{char}}", char).replace("{{user}}", user)
        if name is not None and use_macro:
            s = s.replace("{{name}}", name)
        return s

    bible = read_text(p.f("bible.md")).strip()
    state = read_text(p.f("state.md")).strip()
    card = format_card(sc)
    scene_text = tree.text() if tree.head else ""
    continuing = bool(scene_text)
    prev_src = ""
    if not continuing and idx > 0:
        prev = Tree(p, scenes[idx - 1]["id"])
        prev_src = prev.text() if prev.head else ""
    hay = "\n".join([card, (scene_text or prev_src)[-4000:], steer or ""])
    lfields, ldetail, lskipped = assemble_lore(p, lore, sc, hay, int(B["lore"]), model, char, user)
    if lskipped:
        notes.append(f"{lskipped} triggered lore entries skipped (lore budget {B['lore']})")
    present = sc.get("characters") or []
    if present:
        cast = (f"Characters present in this scene: {', '.join(present)}. Only they appear, speak or act on the page. "
                "Anyone else may only be mentioned or remembered.")
    else:
        cast = ""
        notes.append("scene has no characters list: cast rule not applied (set it with: who NAME, NAME)")
    sw = words(scene_text)
    tw = int(sc.get("target_words") or 0)
    progress = f"Progress: this scene has ~{sw} words so far" + (f" of a ~{tw}-word target." if tw else ".")
    if tw and sw >= tw * 0.9:
        progress += " The scene is at its target length: drive to the outcome and end the scene."
    for name, text in (("bible", bible), ("state", state), ("scene_card", card), ("steer", steer or "")):
        t = p.est(model, text)
        if t > int(B[name]):
            notes.append(f"{name} is ~{t} tokens, over its {B[name]} budget (not truncated)")
    params, extra, ignored = writer_sampling(preset, lambda x: mac(x, char))
    out_seq = ins.get("last_output_sequence") or ins.get("first_output_sequence") or ins.get("output_sequence", "")
    system = mac(preset["sysprompt"].get("content", ""))

    def compose(rb, sb):
        return compose_writer_prompt(PromptInputs(
            rb=rb, sb=sb, scenes=scenes, idx=idx, ins=ins,
            story_string=preset["context"]["story_string"], mac=mac, char=char, user=user,
            bible=bible, state=state, card=card, scene_text=scene_text, continuing=continuing,
            prev_src=prev_src, steer=steer, passage_words=passage_words, lfields=lfields,
            cast=cast, progress=progress, system=system, out_seq=out_seq, sums=p.summaries(),
            summary_cfg=p.cfg["summary"], est=p.est, ratio=p.ratio, model=model, root=p.root))

    ceil, max_comp, src = p.writer_ceiling(preset)
    max_tokens = int(params.get("max_tokens") or 300)
    if max_comp and max_tokens > max_comp:
        notes.append(f"genamt {max_tokens} clamped to model max_completion {max_comp}")
        max_tokens = max_comp
    params["max_tokens"] = max_tokens
    avail = int(ceil * (1 - float(p.cfg["context_safety_margin"]))) - max_tokens
    rb, sb = int(B["recent"]), int(B["summary"])
    prompt, parts, snotes = compose(rb, sb)
    total = p.est(model, prompt)
    while total > avail and (rb > 500 or sb > 500):
        if rb > 500:
            rb = max(500, int(rb * 0.8))
        else:
            sb = max(500, int(sb * 0.8))
        prompt, parts, snotes = compose(rb, sb)
        total = p.est(model, prompt)
    if rb < int(B["recent"]) or sb < int(B["summary"]):
        notes.append(f"shrunk to fit context: recent budget {rb}, summary budget {sb}")
    notes += snotes
    if total > int(p.cfg["prompt_budget"]):
        notes.append(f"prompt ~{total} tokens exceeds soft prompt_budget {p.cfg['prompt_budget']}")
    report = {
        "parts": parts, "total": total, "max_tokens": max_tokens, "ceiling": ceil, "ceiling_source": src,
        "available_for_prompt": avail, "over": total > avail, "notes": notes, "ratio": round(p.ratio(model), 2),
        "lore": ldetail, "char": char, "user": user, "continuing": continuing,
    }
    return prompt, params, extra, ignored, report


def print_report(r, params=None, extra=None):
    print(col("context estimate (chars/token %.2f):" % r["ratio"], "36"))
    for k, v in r["parts"].items():
        print(f"  {k:<12} ~{v}")
    print(f"  {'TOTAL':<12} ~{r['total']}  (+{r['max_tokens']} completion; ceiling {r['ceiling']} from {r['ceiling_source']})")
    print(f"  {{{{char}}}} = {r['char']}   {{{{user}}}} = {r['user']}   mode = {'continue' if r['continuing'] else 'scene start'}")
    if params is not None:
        print("  samplers: " + json.dumps(params) + ("   + " + json.dumps(extra) if extra else ""))
    if r["lore"]:
        print(col("  lore injected:", "36"))
        for line in r["lore"]:
            print("    " + line)
    else:
        print("  lore injected: (none)")
    for n in r["notes"]:
        warn(n)
    if r["over"]:
        print(col("  OVER the context ceiling: trim the bible/state/lore or lower budgets in project.json", "31"))


SCENE_END_RE = re.compile(r"\[\s*SCENE[\s_-]*END\s*\]", re.I)


def clean_continuation(text, finish, continuing):
    t = re.split(r"<\|eot_id\|>|<\|start_header_id\|>", text or "")[0]
    ended = False
    m = SCENE_END_RE.search(t)
    if m:
        ended = True
        t = t[: m.start()]
    trimmed = False
    if finish == "length" and not ended:
        body = t.rstrip()
        ends = list(re.finditer(r"[.!?…][\"'”’)*_]*(?=\s|$)", body))
        if ends and ends[-1].end() > len(body) * 0.3:
            t, trimmed = body[: ends[-1].end()], True
    t = re.sub(r"\n{3,}", "\n\n", t.rstrip())
    if not continuing:
        t = t.lstrip()
    return t, ended, trimmed

