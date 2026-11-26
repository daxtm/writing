"""Logging, file/JSON/text, diff and parse helpers."""

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
from datetime import datetime, timezone
from pathlib import Path

from .config import COLOR

def col(s, code):
    return f"\033[{code}m{s}\033[0m" if COLOR else s


class FatalError(SystemExit):
    """Raised by die(): the message is already on stderr; CLI main exits 1.

    Subclasses SystemExit so existing `except SystemExit` expectations and the
    process exit code are unchanged, while shared operations can catch it and
    turn user-correctable failures into sanitized outcomes instead of killing
    a worker thread (ADR-0007).
    """

    def __init__(self, msg):
        super().__init__(1)
        self.msg = msg


def die(msg):
    print(col("error: ", "31") + msg, file=sys.stderr)
    raise FatalError(msg)


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


def _editor_env():
    """Environment for the editor child process, or None to inherit unchanged.

    In a frozen (PyInstaller) build the bootloader points LD_LIBRARY_PATH at the
    one-file extraction directory, saving the pre-frozen value in
    LD_LIBRARY_PATH_ORIG. The editor is a user-supplied host program and must see
    the host's original library search path, so frozen execution restores it
    (or removes the variable when there was no original value). The parent
    environment is never modified, and source execution is unchanged.
    """
    if not getattr(sys, "frozen", False):
        return None
    env = dict(os.environ)
    orig = os.environ.get("LD_LIBRARY_PATH_ORIG")
    if orig:
        env["LD_LIBRARY_PATH"] = orig
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return env


def edit_text(initial, suffix=".md"):
    ed = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ("nano" if shutil.which("nano") else "vi")
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as f:
        f.write(initial)
        tmp = f.name
    try:
        subprocess.run(shlex.split(ed) + [tmp], check=False, env=_editor_env())
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



# ------------------------------------------------------------ credential redaction

REDACTED = "[redacted]"


def redact_text(text, secrets, repl=REDACTED):
    """Replace every nonempty secret value in `text`; ordinary text is
    returned unchanged byte for byte (ADR-0011: credentials from session,
    saved-project and configured-environment sources never reach results,
    events, logs or persistence)."""
    out = text or ""
    for s in secrets or ():
        if s and s in out:
            out = out.replace(s, repl)
    return out


def redact_obj(obj, secrets, repl=REDACTED):
    """Recursive string redaction for structured records (logs, usage,
    metadata); keys are preserved, values are scrubbed."""
    if isinstance(obj, str):
        return redact_text(obj, secrets, repl)
    if isinstance(obj, dict):
        return {k: redact_obj(v, secrets, repl) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v, secrets, repl) for v in obj]
    return obj


class StreamRedactor:
    """Redaction for split streamed fragments.

    Retains a potential secret-prefix suffix until it is safe to emit; a
    complete secret is never emitted and an unsafe prefix is withheld (and
    retracted when the next fragment completes a match). Feed every chunk;
    call flush() once after the stream ends and emit its remainder."""

    def __init__(self, secrets):
        self.secrets = tuple(s for s in (secrets or ()) if s)
        self.tail = ""

    def _unsafe_prefix_len(self, text):
        """Longest suffix of `text` that is a proper prefix of some secret."""
        best = 0
        for s in self.secrets:
            top = min(len(text), len(s) - 1)
            for k in range(top, best, -1):
                if text[-k:] == s[:k]:
                    best = k
                    break
        return best

    def feed(self, chunk):
        text = self.tail + (chunk or "")
        for s in self.secrets:
            if s in text:
                text = text.replace(s, REDACTED)
        k = self._unsafe_prefix_len(text)
        self.tail = text[len(text) - k:] if k else ""
        return text[:len(text) - k] if k else text

    def flush(self):
        text = self.tail
        self.tail = ""
        for s in self.secrets:
            if s in text:
                text = text.replace(s, REDACTED)
        if text and self._unsafe_prefix_len(text):
            return ""   # never emit an unsafe prefix of a secret
        return text
