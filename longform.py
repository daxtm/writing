#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
"""longform.py - plan-then-collaborate longform fiction pipeline for Featherless.

Writer: text completion (/v1/completions) driven by a SillyTavern master-export preset
(instruct + context + sysprompt + samplers). Planner/summarizer/critic/editor: chat completions.

Every command is its own step. No command runs another one for you.

  init DIR [--preset FILE]     create a project folder; --preset copies a SillyTavern preset in as writer_preset.json
  limits DIR                   fetch your plan + model context limits from Featherless -> limits.json
  bible DIR                    answer fixed questions per section; your answers go into bible.md as written
  outline DIR [--n N]          generate N competing outlines, pick one -> outline.md
  scenes DIR [--force]         break outline.md into scene cards -> scenes.json
  draft DIR [--scene ID]       interactive drafting loop (swipes, steer, edit, rewind, branches, lorebook toggles)
  update-state DIR [--scene ID] [--summary-only]
                               summarize a finished scene and update state.md
  compress DIR --from ID --to ID
                               condense a run of scene summaries into one arc summary
  critique DIR --scene ID      critic-model review of a scene -> critiques/ID.md
  check DIR [--scene ID]       deterministic banned-phrase + repeated n-gram report -> checks/ID.md
  revise DIR --scene ID        passage-by-passage line edit using critiques/ID.md and/or checks/ID.md
  status DIR                   project overview
  export DIR [--out FILE]      write manuscript.md

API key: "api_key" in project.json, or else the environment variable named by "api_key_env"
(default: export FEATHERLESS_API_KEY=...).

Lorebooks: put SillyTavern World Info JSON files, or character cards (V1/V2/V3, as .png or .json) in
DIR/lorebooks/. A card becomes a character lorebook: its description + personality as one entry keyed on
the character's name, plus any embedded character_book entries. Toggle them and mark character books inside the draft loop (lb).
"""

import argparse
import base64
import difflib
import hashlib
import json
import os
import pydoc
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import httpx

# --------------------------------------------------------------------------- defaults

DEFAULT_MODEL = "meta-llama/Llama-3.3-70B-Instruct"

DEFAULT_CONFIG = {
    "title": "Untitled",
    "target_words": 17000,
    "api_base": "https://api.featherless.ai/v1",
    "api_key": "",
    "api_key_env": "FEATHERLESS_API_KEY",
    "max_context_fallback": 32768,
    "context_safety_margin": 0.05,
    "prompt_budget": 16000,
    "chars_per_token_default": 3.5,
    "max_parallel": 1,
    "request_timeout_s": 600,
    "roles": {
        "planner": {"model": DEFAULT_MODEL, "temperature": 0.9, "min_p": 0.05, "max_tokens": 8000,
                    "thinking": True, "thinking_budget": 4000},
        "writer": {
            "model": DEFAULT_MODEL,
            "preset": "writer_preset.json",
            "preset_overrides": {"temp": 1.06},
            "swipes": 2,
            "passage_words": 220,
            "user_name": "Author",
            "absent_character_lore": "reference",
            "lore_match_whole_words": True,
        },
        "summarizer": {"model": DEFAULT_MODEL, "temperature": 0.3, "max_tokens": 8000, "thinking": False},
        "critic": {"model": DEFAULT_MODEL, "temperature": 0.4, "max_tokens": 8000, "thinking": False},
        "editor": {"model": DEFAULT_MODEL, "temperature": 0.6, "min_p": 0.05, "max_tokens": 1600},
    },
    "budget_tokens": {
        "bible": 1800,
        "scene_card": 700,
        "summary": 5000,
        "state": 2500,
        "lore": 2500,
        "recent": 3000,
        "steer": 400,
    },
    "summary": {"detailed_recent_scenes": 3, "detailed_words": 200, "brief_words": 50, "arc_words": 350},
    "banned_phrases": [
        "shivers down",
        "a testament to",
        "barely above a whisper",
        "ministrations",
        "tapestry of",
        "the air was thick with",
        "couldn't help but",
        "maybe, just maybe",
        "sparkling with mischief",
        "a dance of",
        "breath she didn't know",
        "breath he didn't know",
        "eyes widened in",
        "sent a jolt",
    ],
    "ngram": {"n": 5, "min_count": 3, "top": 40},
}

SAMPLING_KEYS = (
    "temperature", "top_p", "top_k", "min_p", "repetition_penalty",
    "presence_penalty", "frequency_penalty", "seed", "stop", "min_tokens", "max_tokens",
)
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}

# SillyTavern sampler fields Featherless has no documented parameter for, with their "off" test.
ST_UNSENDABLE = (
    ("typical_p", lambda v: v not in (None, 1, 1.0)),
    ("tfs", lambda v: v not in (None, 1, 1.0)),
    ("top_a", lambda v: bool(v)),
    ("epsilon_cutoff", lambda v: bool(v)),
    ("eta_cutoff", lambda v: bool(v)),
    ("mirostat_mode", lambda v: bool(v)),
    ("smoothing_factor", lambda v: bool(v)),
    ("xtc_probability", lambda v: bool(v)),
    ("nsigma", lambda v: bool(v)),
    ("dynatemp", lambda v: bool(v)),
    ("no_repeat_ngram_size", lambda v: bool(v)),
    ("penalty_alpha", lambda v: bool(v)),
    ("encoder_rep_pen", lambda v: v not in (None, 1, 1.0)),
    ("guidance_scale", lambda v: v not in (None, 1, 1.0)),
    ("skew", lambda v: bool(v)),
)

BIBLE_TEMPLATE = """# Story bible

## Title
(working title)

## Premise
(2-5 sentences: who, what they want, what stands in the way, what's at stake)

## Source & canon
(fanfic only: fandom, where in canon this sits, the canon facts you rely on, where you deliberately diverge)

## POV & tense
(e.g. close third person, past tense, single POV: NAME)

## Style rules
- (voice, sentence rhythm, dialogue habits, explicitness level, what to dramatize vs summarize)

## Avoid
- (phrases, tropes, habits you don't want)

## Characters
### NAME
- Role:
- Look:
- Voice / speech:
- Wants / fears:
- Relationships:
"""

STATE_TEMPLATE = """# Continuity state

## Characters
- NAME: location - ; condition - ; knows - ; wants - ; relationships -

## Open threads
-

## Established facts
-

## Resolved
-
"""

SUMMARIZER_SYSTEM = (
    "You maintain continuity records for a story in progress. Be factual and specific. "
    "Record only what the text actually establishes. Never invent events, motives or details."
)

CRITIC_SYSTEM = (
    "You are a demanding fiction editor. Report problems only; do not praise. "
    "Quote the exact text for every issue so it can be found."
)

EDITOR_SYSTEM = (
    "You are a line editor. You revise one passage to fix specific listed problems, changing as little as possible. "
    "Preserve voice, POV, tense, events and approximate length unless a listed problem requires otherwise."
)

PLANNER_SYSTEM = (
    "You are a story architect who designs tightly plotted fiction. Every beat you write is a concrete event, "
    "never a theme or a mood."
)

COLOR = sys.stdout.isatty()
LOCK = threading.Lock()


# --------------------------------------------------------------------------- small utils

def col(s, code):
    return f"\033[{code}m{s}\033[0m" if COLOR else s


def die(msg):
    print(col("error: ", "31") + msg, file=sys.stderr)
    sys.exit(1)


def warn(msg):
    print(col("warning: ", "33") + msg)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"{path} is not valid JSON: {e}")


def write_json(path, data):
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_text(path, default=""):
    path = Path(path)
    return path.read_text(encoding="utf-8") if path.exists() else default


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def words(text):
    return len(re.findall(r"\S+", text or ""))


def text_hash(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def tag_instr(tag):
    return (f"Put your final answer between <{tag}> and </{tag}> tags, with nothing else inside them. "
            f"Anything outside the tags is discarded.")


def extract_tagged(text, tag):
    """Text inside the last <tag>...</tag> pair (thinking may mention the tag earlier).
    Falls back to text after the last opening tag (output cut off), then to the whole text. Returns (text, ok)."""
    raw = text or ""
    opens = [m.end() for m in re.finditer(rf"<{tag}>", raw, flags=re.I)]
    closes = [m.start() for m in re.finditer(rf"</{tag}>", raw, flags=re.I)]
    if closes:
        end = closes[-1]
        starts = [o for o in opens if o <= end]
        if starts:
            return raw[starts[-1]:end].strip(), True
    if opens:
        return raw[opens[-1]:].strip(), False
    return raw.strip(), False


def edit_text(initial, suffix=".md"):
    ed = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ("nano" if shutil.which("nano") else "vi")
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as f:
        f.write(initial)
        tmp = f.name
    try:
        subprocess.run(shlex.split(ed) + [tmp], check=False)
        return Path(tmp).read_text(encoding="utf-8")
    finally:
        os.unlink(tmp)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "x"


def save_input(root, kind, text):
    """Keep everything typed in $EDITOR: latest at inputs/KIND.md, every version in inputs/history/."""
    root = Path(root)
    write_text(root / "inputs" / f"{kind}.md", text)
    write_text(root / "inputs" / "history" / f"{kind}_{stamp()}.md", text)


def edit_saved(p, kind, initial):
    """edit_text, then save what was typed before anything else can fail."""
    text = edit_text(initial)
    save_input(p.root, kind, text)
    return text


def keep_lead(old, new):
    """Preserve the leading whitespace of a continuation passage across edits."""
    lead = re.match(r"\s*", old).group(0)
    return lead + new.lstrip() if lead else new


def page(text):
    if COLOR:
        pydoc.pager(text)
    else:
        print(text)


def ask(prompt):
    try:
        return input(prompt)
    except EOFError:
        return "q"


def word_diff(a, b):
    ta = re.findall(r"\S+|\s+", a)
    tb = re.findall(r"\S+|\s+", b)
    sm = difflib.SequenceMatcher(a=ta, b=tb, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            out.append("".join(ta[i1:i2]))
            continue
        if i2 > i1:
            out.append(col("[-" + "".join(ta[i1:i2]) + "-]", "31"))
        if j2 > j1:
            out.append(col("{+" + "".join(tb[j1:j2]) + "+}", "32"))
    return "".join(out)


def line_diff(a, b, la="before", lb="after"):
    out = []
    for line in difflib.unified_diff(a.splitlines(), b.splitlines(), la, lb, lineterm=""):
        if line.startswith("+") and not line.startswith("+++"):
            out.append(col(line, "32"))
        elif line.startswith("-") and not line.startswith("---"):
            out.append(col(line, "31"))
        else:
            out.append(line)
    return "\n".join(out) if out else "(no changes)"


def parse_sections(text, names):
    pat = r"^\s*=+\s*(" + "|".join(re.escape(n) for n in names) + r")\s*=+\s*$"
    parts = re.split(pat, text, flags=re.M | re.I)
    res = {}
    for k in range(1, len(parts) - 1, 2):
        res[parts[k].upper()] = parts[k + 1].strip()
    return res if all(n in res and res[n] for n in names) else None


def name_re(n):
    return r"(?<!\w)" + re.escape(n) + r"(?!\w)"


# --------------------------------------------------------------------------- project

class Project:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        if not (self.root / "project.json").exists():
            die(f"no project.json in {self.root} (run: init {self.root})")
        self.cfg = deep_merge(DEFAULT_CONFIG, read_json(self.root / "project.json", {}))

    def f(self, *parts):
        return self.root.joinpath(*parts)

    def scenes(self):
        return read_json(self.f("scenes.json"), [])

    def save_scenes(self, scenes):
        write_json(self.f("scenes.json"), scenes)

    def scene_index(self, scenes, sid):
        for i, s in enumerate(scenes):
            if s["id"] == sid:
                return i
        die(f"no scene with id {sid}")

    def summaries(self):
        return read_json(self.f("summaries.json"), {"scenes": {}, "arcs": []})

    def save_summaries(self, d):
        write_json(self.f("summaries.json"), d)

    # tokens
    def ratio(self, model):
        c = read_json(self.f("calib.json"), {}).get(model)
        if c and c.get("tokens", 0) > 500:
            return c["chars"] / c["tokens"]
        return float(self.cfg["chars_per_token_default"])

    def est(self, model, text):
        return int(len(text or "") / self.ratio(model)) + 1

    def record_calib(self, model, chars, tokens):
        if not tokens:
            return
        with LOCK:
            d = read_json(self.f("calib.json"), {})
            c = d.get(model, {"chars": 0, "tokens": 0})
            c["chars"] += chars
            c["tokens"] += tokens
            d[model] = c
            write_json(self.f("calib.json"), d)

    def ceiling(self, model):
        fb = int(self.cfg["max_context_fallback"])
        lim = read_json(self.f("limits.json"), None)
        if not lim:
            return fb, None, "max_context_fallback (no limits.json; run: limits)"
        plan_max = (lim.get("plan") or {}).get("max_context_length")
        m = (lim.get("models") or {}).get(model) or {}
        vals = [v for v in (plan_max, m.get("context")) if isinstance(v, int) and v > 0]
        mc = m.get("max_completion") if isinstance(m.get("max_completion"), int) else None
        if not vals:
            return fb, mc, "max_context_fallback (limits.json has no value for this model)"
        return min(vals), mc, "limits.json"

    def log_call(self, rec):
        with LOCK:
            with open(self.f("calls.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # writer preset
    def preset_path(self):
        p = Path(self.cfg["roles"]["writer"]["preset"]).expanduser()
        return p if p.is_absolute() else self.f(str(p))

    def preset(self):
        path = self.preset_path()
        if not path.exists():
            die(f"writer preset not found: {path} (copy your SillyTavern preset there, or run: init {self.root} --preset FILE)")
        d = read_json(path)
        for k in ("instruct", "context", "sysprompt", "preset"):
            if k not in d:
                die(f"{path} is not a SillyTavern master export (missing '{k}')")
        d = json.loads(json.dumps(d))
        d["preset"].update(self.cfg["roles"]["writer"].get("preset_overrides") or {})
        return d

    def writer_ceiling(self, preset):
        model = self.cfg["roles"]["writer"]["model"]
        ceil, mc, src = self.ceiling(model)
        ml = preset["preset"].get("max_length")
        if isinstance(ml, int) and 0 < ml < ceil:
            return ml, mc, f"preset max_length (below {src} value {ceil})"
        return ceil, mc, src


# --------------------------------------------------------------------------- API

class HttpErr(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body[:800]}")
        self.status = status


class NoAnswerErr(Exception):
    """The model returned no answer (e.g. thinking used the whole token allowance)."""


def split_thinking(content, reasoning=""):
    """Separate a reply into (answer, thinking, closed).
    Thinking comes either in the server's reasoning field or inline before </think>
    (Qwen/GLM templates open <think> in the prompt, so the reply may start mid-thought)."""
    c = content or ""
    closes = list(re.finditer(r"</think>", c, flags=re.I))
    if closes:
        think = re.sub(r"^\s*<think>", "", c[:closes[-1].start()], flags=re.I)
        return c[closes[-1].end():].strip(), (reasoning + "\n" + think).strip(), True
    if re.match(r"\s*<think>", c, flags=re.I):
        return "", (reasoning + "\n" + c).strip(), False
    return c.strip(), (reasoning or "").strip(), True


class Progress:
    """One live status line on stderr while a chat call streams: thinking vs answer, approx tokens, seconds."""

    def __init__(self, label):
        self.label, self.t0, self.last = label, time.time(), 0.0
        self.think, self.write = 0, 0

    def __call__(self, phase, nchars):
        if phase == "thinking":
            self.think += nchars
        else:
            self.write += nchars
        now_t = time.time()
        if now_t - self.last >= 0.25:
            self.last = now_t
            self.show()

    def show(self):
        msg = (f"  {self.label}: thinking ~{int(self.think / 3.5)} tok, answer ~{int(self.write / 3.5)} tok, "
               f"{time.time() - self.t0:.0f}s")
        print("\r" + msg + "   ", end="", file=sys.stderr, flush=True)

    def done(self):
        self.show()
        print(file=sys.stderr, flush=True)


class Api:
    def __init__(self, p):
        self.p = p
        key = str(p.cfg.get("api_key") or "").strip()
        if not key:
            env = str(p.cfg.get("api_key_env") or "")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env):
                die('project.json "api_key_env" must be the NAME of an environment variable (e.g. FEATHERLESS_API_KEY), '
                    'not the key itself. Put the key in "api_key" instead.')
            key = os.environ.get(env, "").strip()
            if not key:
                die(f'no API key: set "api_key" in {p.f("project.json")}, or export {env}=...')
        self.base = p.cfg["api_base"].rstrip("/")
        self.headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        self.timeout = httpx.Timeout(float(p.cfg["request_timeout_s"]), connect=30.0)
        self.extra_ok = True

    def get(self, path):
        def once():
            r = httpx.get(self.base + path, headers=self.headers, timeout=self.timeout)
            if r.status_code != 200:
                raise HttpErr(r.status_code, r.text)
            return r.json()
        return self._retry(once)

    def _retry(self, fn, on_retry=None):
        delay = 2.0
        for attempt in range(7):
            try:
                return fn()
            except HttpErr as e:
                if e.status not in RETRY_STATUS or attempt == 6:
                    raise
                why = f"HTTP {e.status}"
            except httpx.TransportError as e:
                if attempt == 6:
                    raise
                why = type(e).__name__
            if on_retry:
                on_retry(why, delay)
            else:
                print(col(f"  [{why}; retrying in {delay:.0f}s]", "33"), flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 30.0)

    def _post(self, url, body, stream_cb, kind, progress=None, thinking=False):
        """Always streams, so long generations never sit silent past the read timeout and one bad chunk
        can't sink a whole reply. kind 'chat' reads delta content (+ reasoning fields), 'text' reads choice text.
        Returns (content, finish_reason, usage, reasoning, bad_chunks)."""
        parts, rparts, bad, finish, usage = [], [], [], None, {}
        closed = False
        with httpx.stream("POST", url, headers=self.headers, json=dict(body, stream=True), timeout=self.timeout) as r:
            if r.status_code != 200:
                r.read()
                raise HttpErr(r.status_code, r.text)
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    j = json.loads(data)
                except json.JSONDecodeError:
                    bad.append(data)
                    continue
                if j.get("usage"):
                    usage = j["usage"]
                chs = j.get("choices") or []
                if not chs:
                    continue
                delta = chs[0].get("delta") or {}
                if kind == "chat":
                    rr = delta.get("reasoning_content") or delta.get("reasoning")
                    if rr:
                        rparts.append(rr)
                        if progress:
                            progress("thinking", len(rr))
                t = delta.get("content") if kind == "chat" else chs[0].get("text")
                if t:
                    parts.append(t)
                    if stream_cb:
                        stream_cb(t)
                    if progress:
                        if thinking and not closed and "</think>" in "".join(parts[-50:]).lower():
                            closed = True
                        progress("thinking" if thinking and not closed else "answer", len(t))
                if chs[0].get("finish_reason"):
                    finish = chs[0]["finish_reason"]
        return "".join(parts), finish, usage, "".join(rparts), bad

    def _report_stream_problems(self, role, finish, bad):
        notes = []
        if bad:
            notes.append(f"{len(bad)} malformed chunk(s) from the server; text may be missing (raw chunks logged in calls.jsonl)")
        if finish is None:
            notes.append("the stream ended without a finish reason; the reply may be cut off")
        for n in notes:
            warn(f"{role}: {n}")
        return notes

    @staticmethod
    def _on_retry(why, delay):
        print(col(f"\n  [{why}; retrying in {delay:.0f}s]", "33"), flush=True)

    def chat(self, role, messages, max_tokens=None, stream_cb=None, progress=True):
        """Returns (answer, finish_reason, usage). Thinking never reaches the answer: it is split off
        by the reasoning field or </think>, and an unfinished thought raises NoAnswerErr."""
        rc = self.p.cfg["roles"][role]
        body = {"model": rc["model"], "messages": messages}
        for k in SAMPLING_KEYS:
            if k in rc:
                body[k] = rc[k]
        if max_tokens is not None:
            body["max_tokens"] = int(max_tokens)
        kwargs = dict(rc.get("chat_template_kwargs") or {})
        think = rc.get("thinking")
        if think is not None:
            kwargs.setdefault("enable_thinking", bool(think))
            if think and rc.get("thinking_budget"):
                kwargs.setdefault("thinking_budget", int(rc["thinking_budget"]))
        if kwargs:
            body["chat_template_kwargs"] = kwargs
        thinking_on = bool(kwargs.get("enable_thinking", kwargs.get("thinking", think is None)))
        t0 = time.time()
        prog = Progress(f"{role} ({rc['model']})") if progress and stream_cb is None else None
        try:
            content, finish, usage, reasoning, bad = self._retry(
                lambda: self._post(self.base + "/chat/completions", body, stream_cb, "chat", prog, thinking_on),
                self._on_retry)
        finally:
            if prog:
                prog.done()
        stream_notes = self._report_stream_problems(role, finish, bad)
        answer, thought, closed = split_thinking(content, reasoning)
        if thinking_on and not reasoning and "</think>" not in content.lower() and finish == "length":
            answer, thought, closed = "", content, False  # template opened <think>; the model never closed it
        self.p.record_calib(rc["model"], sum(len(m["content"]) for m in messages), usage.get("prompt_tokens"))
        self.p.log_call({
            "time": now(), "role": role, "model": rc["model"], "endpoint": "chat", "seconds": round(time.time() - t0, 1),
            "params": {k: v for k, v in body.items() if k not in ("messages", "model")},
            "messages": messages, "output": answer, "thinking": thought, "raw_content": content,
            "finish_reason": finish, "usage": usage, "stream_problems": stream_notes, "bad_chunks": bad,
        })
        if not answer:
            if not closed:
                raise NoAnswerErr(
                    f"{role} ({rc['model']}) was still thinking when it hit max_tokens {body.get('max_tokens', '?')}, "
                    f"so there is no answer. Raise roles.{role}.max_tokens, lower roles.{role}.thinking_budget, or set "
                    f"roles.{role}.thinking to false in {self.p.f('project.json')}.")
            raise NoAnswerErr(f"{role} ({rc['model']}) returned an empty answer (finish_reason={finish}).")
        if finish == "length":
            warn(f"{role} answer hit max_tokens {body.get('max_tokens', '?')}; it may be cut off")
        return answer, finish, usage

    def complete(self, role, prompt, params, extra=None, stream_cb=None, meta=None):
        """Text completion. `extra` holds params Featherless doesn't document (DRY); if the
        server rejects them they are dropped for the rest of the session, with a warning."""
        rc = self.p.cfg["roles"][role]
        body = {"model": rc["model"], "prompt": prompt, **params}
        sent_extra = bool(extra) and self.extra_ok
        if sent_extra:
            body.update(extra)
        url = self.base + "/completions"
        t0 = time.time()
        try:
            text, finish, usage, _, bad = self._retry(lambda: self._post(url, body, stream_cb, "text"), self._on_retry)
        except HttpErr as e:
            if sent_extra and e.status in (400, 422) and any(k.split("_")[0] in str(e).lower() for k in extra):
                with LOCK:
                    if self.extra_ok:
                        self.extra_ok = False
                        warn("server rejected " + ", ".join(extra) + f" ({e}); sending without them for this session")
                body = {k: v for k, v in body.items() if k not in extra}
                sent_extra = False
                text, finish, usage, _, bad = self._retry(lambda: self._post(url, body, stream_cb, "text"), self._on_retry)
            else:
                raise
        stream_notes = self._report_stream_problems(role, finish, bad)
        self.p.record_calib(rc["model"], len(prompt), usage.get("prompt_tokens"))
        self.p.log_call({
            "time": now(), "role": role, "model": rc["model"], "endpoint": "completions", "seconds": round(time.time() - t0, 1),
            "params": {k: v for k, v in body.items() if k not in ("prompt", "model")},
            "extra_sent": sent_extra, "extra": extra or {}, "meta": meta or {},
            "prompt": prompt, "output": text, "finish_reason": finish, "usage": usage,
            "stream_problems": stream_notes, "bad_chunks": bad,
        })
        return text, finish, usage

    def many(self, fn, n):
        workers = max(1, min(n, int(self.p.cfg["max_parallel"])))
        results = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(fn) for _ in range(n)]
            for k, fut in enumerate(as_completed(futs), 1):
                try:
                    results.append(fut.result())
                    print(col(f"  candidate {k}/{n} done", "2"), flush=True)
                except Exception as e:  # noqa: BLE001
                    print(col(f"  candidate {k}/{n} failed: {type(e).__name__}: {e}", "31"), flush=True)
                    self.p.log_call({"time": now(), "candidate_failed": f"{type(e).__name__}: {e}"})
        return results

    def chat_many(self, role, messages, n, max_tokens=None):
        one_at_a_time = max(1, min(n, int(self.p.cfg["max_parallel"]))) == 1
        return self.many(lambda: self.chat(role, messages, max_tokens, progress=one_at_a_time), n)


# --------------------------------------------------------------------------- tree

class Tree:
    """Branching passage tree. Each node has `sep`: the text placed between it and its parent.
    Text-completion continuations use sep "" and keep their own leading whitespace."""

    def __init__(self, p, sid):
        self.path = p.f("trees", f"{sid}.json")
        self.d = read_json(self.path, {"nodes": {}, "head": None, "counter": 0})

    @property
    def head(self):
        return self.d["head"]

    @head.setter
    def head(self, nid):
        self.d["head"] = nid

    def node(self, nid):
        return self.d["nodes"][nid]

    def add(self, parent, text, **meta):
        self.d["counter"] += 1
        nid = f"n{self.d['counter']}"
        self.d["nodes"][nid] = {"id": nid, "parent": parent, "text": text, "created": now(), "history": [], **meta}
        return nid

    def children(self, nid):
        kids = [n for n in self.d["nodes"].values() if n["parent"] == nid]
        return [n["id"] for n in sorted(kids, key=lambda n: int(n["id"][1:]))]

    def chain(self, nid="__head__"):
        nid = self.head if nid == "__head__" else nid
        out = []
        while nid is not None:
            out.append(nid)
            nid = self.d["nodes"][nid]["parent"]
        return list(reversed(out))

    def text(self, nid="__head__"):
        out = ""
        for k, i in enumerate(self.chain(nid)):
            n = self.d["nodes"][i]
            t = n["text"]
            if k == 0:
                out = t.lstrip()
                continue
            sep = n.get("sep", "\n\n")
            if sep == "" and t and not t[0].isspace() and out and out[-1] in ".!?…\"'”’*":
                sep = " "
            out += sep + (t if sep == "" or sep == " " else t.lstrip())
        return out

    def delete(self, nid):
        if self.children(nid):
            return False
        if self.head == nid:
            self.head = self.d["nodes"][nid]["parent"]
        del self.d["nodes"][nid]
        return True

    def save(self):
        write_json(self.path, self.d)


# --------------------------------------------------------------------------- lorebooks

def read_card_png(path):
    """Card JSON from a SillyTavern character PNG (tEXt/iTXt chunk 'ccv3' preferred, then 'chara')."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos, found = 8, {}
    while pos + 8 <= len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"tEXt":
            key, _, val = body.partition(b"\x00")
            found[key.decode("latin-1").lower()] = val
        elif ctype == b"iTXt":
            key, _, rest = body.partition(b"\x00")
            if len(rest) < 2:
                continue
            compressed, rest = rest[0], rest[2:]
            _lang, _, rest = rest.partition(b"\x00")
            _tkey, _, val = rest.partition(b"\x00")
            try:
                found[key.decode("latin-1").lower()] = zlib.decompress(val) if compressed else val
            except zlib.error:
                continue
        elif ctype == b"IEND":
            break
    for key in ("ccv3", "chara"):
        if key in found:
            try:
                return json.loads(base64.b64decode(found[key]).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
    return None


def card_fields(d):
    """The character fields of a V2/V3 card (under 'data') or a V1 card (top level); None if not a card."""
    if not isinstance(d, dict):
        return None
    if isinstance(d.get("data"), dict) and ("name" in d["data"] or "character_book" in d["data"]):
        return d["data"]
    if "name" in d and ("description" in d or "personality" in d) and "entries" not in d:
        return d
    return None


def parse_book(path):
    """Read a SillyTavern World Info export, a character card (.png or .json), or a bare entry list."""
    path = Path(path)
    if path.suffix.lower() == ".png":
        d = read_card_png(path)
        if d is None:
            warn(f"{path.name}: no character card data found in this PNG")
            return None, []
    else:
        d = read_json(path, {})
    card = card_fields(d)
    card_name, raw, synth = None, [], []
    if card is not None:
        card_name = (card.get("name") or path.stem).strip()
        raw = (card.get("character_book") or {}).get("entries", [])
        desc = (card.get("description") or "").strip()
        pers = (card.get("personality") or "").strip()
        content = desc + (("\n\nPersonality: " + pers) if pers else "")
        if content.strip():
            keys = [card_name] + ([card_name.split()[0]] if len(card_name.split()) > 1 else [])
            synth.append({"name": "card description", "keys": keys, "secondary": [], "content": content,
                          "enabled": True, "constant": False, "selective": False, "logic": 0, "order": 100,
                          "before": False, "case": None, "whole": None})
    elif isinstance(d, dict) and "entries" in d:
        raw = d["entries"]
    elif isinstance(d, list):
        raw = d
    if isinstance(raw, dict):
        raw = list(raw.values())
    out = []
    for e in raw:
        if not isinstance(e, dict):
            continue

        def keylist(v):
            if isinstance(v, str):
                v = v.split(",")
            return [str(k).strip() for k in (v or []) if str(k).strip()]

        pos = e.get("position", 0)
        out.append({
            "name": e.get("comment") or e.get("name") or "",
            "keys": keylist(e.get("key", e.get("keys", []))),
            "secondary": keylist(e.get("keysecondary", e.get("secondary_keys", []))),
            "content": e.get("content") or "",
            "enabled": bool(e.get("enabled", True)) and not bool(e.get("disable", False)),
            "constant": bool(e.get("constant", False)),
            "selective": bool(e.get("selective", False)),
            "logic": int(e.get("selectiveLogic", 0) or 0),
            "order": int(e.get("order", e.get("insertion_order", 100)) or 100),
            "before": pos in (0, "before_char"),
            "case": e.get("caseSensitive", e.get("case_sensitive")),
            "whole": e.get("matchWholeWords"),
        })
    return card_name, synth + out


def key_match(key, hay, case, whole):
    m = re.fullmatch(r"/(.+)/([a-z]*)", key)
    if m:
        try:
            return re.search(m.group(1), hay, re.I if "i" in m.group(2) else 0) is not None
        except re.error:
            return False
    pat = name_re(key) if whole else re.escape(key)
    return re.search(pat, hay, 0 if case else re.I) is not None


def entry_triggered(e, hay, whole_default):
    case = bool(e["case"]) if e["case"] is not None else False
    whole = e["whole"] if isinstance(e["whole"], bool) else whole_default
    if not any(key_match(k, hay, case, whole) for k in e["keys"]):
        return False
    if e["selective"] and e["secondary"]:
        hits = [key_match(k, hay, case, whole) for k in e["secondary"]]
        return {0: any(hits), 1: not all(hits), 2: not any(hits), 3: all(hits)}.get(e["logic"], any(hits))
    return True


def name_variants(name, aliases):
    out = [name] + [a for a in aliases if a]
    if name and len(name.split()) > 1:
        out.append(name.split()[0])
    return [v for v in out if v]


def is_present(name, aliases, present):
    blob = " | ".join(present or [])
    return any(re.search(name_re(v), blob, re.I) for v in name_variants(name, aliases))


def pov_name(sc):
    present = sc.get("characters") or []
    pov = (sc.get("pov") or "").strip()
    for c in present:
        if pov and re.search(name_re(c), pov, re.I):
            return c
    for c in present:
        first = c.split()[0] if c.split() else c
        if pov and first and re.search(name_re(first), pov, re.I):
            return c
    if pov and len(pov.split()) <= 3 and not re.search(r"person|third|first|second|omniscient|close|limited|pov", pov, re.I):
        return pov
    return present[0] if present else "Narrator"


class Lore:
    def __init__(self, p, scenes):
        self.p = p
        self.dir = p.f("lorebooks")
        self.reg_path = p.f("lorebooks.json")
        self.reg = read_json(self.reg_path, {"books": {}})
        self.cache = {}
        self.sync(scenes)

    def sync(self, scenes):
        self.dir.mkdir(exist_ok=True)
        known = []
        for s in scenes:
            known += s.get("characters") or []
        changed = False
        for path in sorted(p for p in self.dir.iterdir() if p.suffix.lower() in (".json", ".png")):
            if path.name in self.reg["books"]:
                continue
            card_name, entries = parse_book(path)
            meta = {"on": False, "kind": "world", "character": "", "aliases": []}
            if card_name:
                meta.update(kind="character", character=card_name)
            else:
                stem = re.sub(r"[^a-z0-9]+", " ", path.stem.lower()).split()
                for name in known:
                    toks = name.lower().split()
                    if stem and toks and stem[0] == toks[0]:
                        meta.update(kind="character", character=name)
                        break
            self.reg["books"][path.name] = meta
            changed = True
            print(f"new lorebook {path.name}: {meta['kind']}{' ' + meta['character'] if meta['character'] else ''}, {len(entries)} entries, off")
        if changed:
            self.save()

    def save(self):
        write_json(self.reg_path, self.reg)

    def books(self):
        return [(n, m) for n, m in sorted(self.reg["books"].items()) if (self.dir / n).exists()]

    def entries(self, fname):
        if fname not in self.cache:
            self.cache[fname] = parse_book(self.dir / fname)[1]
        return self.cache[fname]

    def char_name(self, fname, meta):
        return meta.get("character") or Path(fname).stem

    def active(self):
        return [n for n, m in self.books() if m.get("on")]

    def absent_mentions(self, sc, text):
        present = sc.get("characters") or []
        out = set()
        for fname, meta in self.books():
            if meta.get("kind") != "character":
                continue
            name = self.char_name(fname, meta)
            aliases = meta.get("aliases", [])
            if is_present(name, aliases, present):
                continue
            if any(re.search(name_re(v), text, re.I) for v in name_variants(name, aliases)):
                out.add(name)
        return sorted(out)


def assemble_lore(p, lore, sc, hay, budget, model, pov, user):
    """Returns story-string fields (wiBefore, description, wiAfter), detail lines, skipped count."""
    rc = p.cfg["roles"]["writer"]
    present = sc.get("characters") or []
    mode = rc.get("absent_character_lore", "reference")
    whole_default = bool(rc.get("lore_match_whole_words", True))
    rank = {"description": 0, "present": 1, "wiBefore": 2, "wiAfter": 2, "absent": 3}
    cands, detail = [], []
    for fname, meta in lore.books():
        if not meta.get("on"):
            continue
        kind = meta.get("kind", "world")
        cname = lore.char_name(fname, meta) if kind == "character" else ""
        if kind == "character":
            aliases = meta.get("aliases", [])
            if is_present(cname, aliases, [pov]):
                section = "description"
            elif is_present(cname, aliases, present):
                section = "present"
            elif mode == "exclude":
                detail.append(f"skipped {fname}: {cname} not in scene (absent_character_lore=exclude)")
                continue
            else:
                section = "absent"
        for e in lore.entries(fname):
            if not e["enabled"] or not e["content"].strip():
                continue
            hit = entry_triggered(e, hay, whole_default)
            if kind == "character" and section == "absent":
                if not hit:
                    continue  # an absent character's constant entries never load
            elif not (e["constant"] or hit):
                continue
            sec = section if kind == "character" else ("wiBefore" if e["before"] else "wiAfter")
            content = e["content"].replace("{{char}}", cname or pov).replace("{{user}}", user)
            label = e["name"] or (e["keys"][0] if e["keys"] else "?")
            cands.append({"sec": sec, "prio": (rank[sec], 0 if e["constant"] else 1, -e["order"]),
                          "order": e["order"], "content": content.strip(), "book": fname, "label": label, "char": cname})
    cands.sort(key=lambda c: c["prio"])
    used, picked, skipped = 0, [], 0
    for c in cands:
        t = p.est(model, c["content"])
        if used + t > budget:
            skipped += 1
            continue
        used += t
        picked.append(c)
        detail.append(f"{c['sec']:<11} {c['book']} / {c['label']}")

    def join(secs, fmt=lambda c: c["content"]):
        items = sorted((c for c in picked if c["sec"] in secs), key=lambda c: c["order"])
        return "\n".join(fmt(c) for c in items)

    absent = join({"absent"}, lambda c: f"[{c['char']}] {c['content']}")
    after = "\n".join(x for x in (join({"present"}), join({"wiAfter"})) if x)
    if absent:
        after = (after + "\n\n" if after else "") + (
            "The following characters are NOT in this scene. Reference only: they must not appear, speak or act on the page.\n"
            + absent)
    fields = {"wiBefore": join({"wiBefore"}), "description": join({"description"}), "wiAfter": after}
    return fields, detail, skipped


# --------------------------------------------------------------------------- writer prompt

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


def tail_trim(p, model, text, budget, marker="..."):
    chars = int(budget * p.ratio(model))
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


def layered_summary(p, scenes, idx, budget, model):
    sums = p.summaries()
    cfg = p.cfg["summary"]
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
            notes.append(f"{s['id']} has no summary (run: update-state {p.root} --scene {s['id']})")
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
    while p.est(model, text) > budget and order:
        detailed.discard(order.pop(0))
        text = render(indexed, detailed, dropped)
    while p.est(model, text) > budget and len(indexed) > 1:
        indexed.pop(0)
        dropped += 1
        text = render(indexed, detailed, dropped)
    if dropped:
        notes.append(f"summary over budget: {dropped} oldest entries dropped (run: compress)")
    return text, notes


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
        summary, snotes = layered_summary(p, scenes, idx, sb, model)
        scenario = bible
        if summary:
            scenario += "\n\nStory so far:\n" + summary
        scenario += "\n\nContinuity state:\n" + (state or "(none yet)")
        fields = {
            "system": system, "wiBefore": mac(lfields["wiBefore"]), "description": mac(lfields["description"]),
            "personality": "", "persona": "", "scenario": mac(scenario), "wiAfter": mac(lfields["wiAfter"]),
            "mesExamples": "", "char": char, "user": user,
        }
        story = render_story_string(preset["context"]["story_string"], fields)
        a = [card]
        if cast:
            a.append(cast)
        a.append(progress)
        if not continuing and prev_src:
            a.append("End of the previous scene (context only; this scene begins now):\n" + tail_trim(p, model, prev_src, rb))
        if not continuing and idx == 0:
            a.append("This is the opening of the story.")
        if steer:
            a.append("Direction for this passage: " + steer)
        a.append(
            f"Write this scene as prose from {char}'s point of view, following the POV, tense and style rules in the scenario. "
            + ("Continue from exactly where the text leaves off" if continuing else "Begin the scene")
            + f", about {passage_words} words. Never repeat what is already written. Stay inside this scene. "
            "When the scene's outcome has been reached, finish at a natural stopping point and write [SCENE END] on its own line."
        )
        author = mac("\n\n".join(a))
        prefill = tail_trim(p, model, scene_text, rb, marker="") if continuing else ""
        prompt = story + mac(ins.get("input_sequence", ""), user) + author + ins.get("input_suffix", "") + mac(out_seq, char) + prefill
        parts = {
            "sysprompt": p.est(model, system), "bible": p.est(model, bible), "summary": p.est(model, summary),
            "state": p.est(model, state),
            "lore": p.est(model, lfields["wiBefore"] + lfields["description"] + lfields["wiAfter"]),
            "author_turn": p.est(model, author), "prefill": p.est(model, prefill),
        }
        return prompt, parts, snotes

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


# --------------------------------------------------------------------------- commands

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
  l N          set target passage length in words for this session
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


def show_candidate(tree, k, nid, with_text):
    n = tree.node(nid)
    flags = []
    if n.get("ended"):
        flags.append("signals SCENE END")
    if n.get("trimmed"):
        flags.append("trimmed at length cutoff")
    if n.get("absent"):
        flags.append(col("mentions absent: " + ", ".join(n["absent"]), "33"))
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
                if tree.head:
                    page("\n\n".join(f"--- {i} ---\n{tree.node(i)['text'].strip()}" for i in tree.chain()))
                else:
                    print("(empty)")
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


STOP = set("the a an and or but of to in on at for with as by from that this it is was were be been he she they "
           "his her their i you we my your our him them its not no so then than there".split())


def cmd_check(p, args):
    scenes = p.scenes()
    targets = [scenes[p.scene_index(scenes, args.scene)]] if args.scene else scenes
    banned = [b for b in p.cfg["banned_phrases"] if b.strip()]
    ng = p.cfg["ngram"]
    n, min_count, top = int(ng["n"]), int(ng["min_count"]), int(ng["top"])
    lines = [f"# Check {'scene ' + args.scene if args.scene else 'all scenes'} ({now()})", "", "## Banned phrases", ""]
    counts, where = {}, {}
    hits = 0
    for s in targets:
        tree = Tree(p, s["id"])
        if not tree.head:
            continue
        for nid in tree.chain():
            t = tree.node(nid)["text"]
            for b in banned:
                for m in re.finditer(re.escape(b), t, re.I):
                    hits += 1
                    a, z = max(0, m.start() - 50), min(len(t), m.end() + 50)
                    snippet = re.sub(r"\s+", " ", t[a:z])
                    lines.append(f'- {s["id"]}/{nid}: "{b}" ... {snippet} ...')
        toks = re.findall(r"[a-z']+", tree.text().lower())
        for k in range(len(toks) - n + 1):
            g = tuple(toks[k: k + n])
            if sum(1 for w in g if w in STOP) >= n - 1:
                continue
            counts[g] = counts.get(g, 0) + 1
            where.setdefault(g, set()).add(s["id"])
    if not hits:
        lines.append("(none)")
    lines += ["", f"## Repeated {n}-grams (count >= {min_count})", ""]
    rep = sorted(((c, g) for g, c in counts.items() if c >= min_count), reverse=True)[:top]
    if rep:
        for c, g in rep:
            lines.append(f'- {c}x "{" ".join(g)}" in {", ".join(sorted(where[g]))}')
    else:
        lines.append("(none)")
    report = "\n".join(lines) + "\n"
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


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, **kw):
        sp = sub.add_parser(name, **kw)
        sp.add_argument("dir", help="project directory")
        return sp

    sp = add("init")
    sp.add_argument("--preset", help="SillyTavern master-export preset JSON to copy in as writer_preset.json")
    add("limits")
    add("bible")
    sp = add("outline")
    sp.add_argument("--n", type=int, default=3, help="number of candidates (default 3)")
    sp.add_argument("--notes", default="", help="extra direction for the planner")
    sp = add("scenes")
    sp.add_argument("--force", action="store_true")
    sp = add("draft")
    sp.add_argument("--scene")
    sp = add("update-state")
    sp.add_argument("--scene")
    sp.add_argument("--summary-only", action="store_true")
    sp = add("compress")
    sp.add_argument("--from", dest="from_id", required=True)
    sp.add_argument("--to", dest="to_id", required=True)
    sp.add_argument("--replace", action="store_true")
    sp = add("critique")
    sp.add_argument("--scene", required=True)
    sp = add("check")
    sp.add_argument("--scene")
    sp = add("revise")
    sp.add_argument("--scene", required=True)
    add("status")
    sp = add("export")
    sp.add_argument("--out")
    args = ap.parse_args()

    if args.cmd == "init":
        return cmd_init(args)
    p = Project(args.dir)
    {
        "limits": cmd_limits, "bible": cmd_bible, "outline": cmd_outline, "scenes": cmd_scenes, "draft": cmd_draft,
        "update-state": cmd_update_state, "compress": cmd_compress, "critique": cmd_critique,
        "check": cmd_check, "revise": cmd_revise, "status": cmd_status, "export": cmd_export,
    }[args.cmd](p, args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\naborted")
        sys.exit(130)
    except (HttpErr, NoAnswerErr) as e:
        die(str(e))
