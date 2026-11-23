"""Fixed-clock CLI fixtures for continuity/review/export parity (offline).

Runs the cmd_* implementations in-process with a scripted fake Api, scripted
answers, a built-in editor replacement (never a terminal or external editor)
and a frozen clock, capturing the transcript and every saved file. Both the
headless parity tests and the offscreen button journey import this module;
the fixture output freezes current CLI behavior before any extraction.
"""

import contextlib
import io
import re
import types
from pathlib import Path

import longform_core.commands as commands
import longform_core.utils as utils

NOW = "2026-01-01T00:00:00+00:00"
STAMP = "20260101-000000"

TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}")
STAMP_RE = re.compile(r"\d{8}-\d{6}")
ROOT_RE = re.compile(r"/tmp[^\s'\"]*(?=tmp|pytest|test)?[^\s'\"]*")


def normalize(text):
    """Normalize only generated timestamps/stamps; never content or order."""
    return STAMP_RE.sub("(STAMP)", TS_RE.sub("(TS)", text or ""))


def snapshot(root):
    """Every saved file under root, bytes normalized; calls.jsonl excluded."""
    out = {}
    for f in sorted(Path(root).rglob("*")):
        if f.is_file() and f.name != "calls.jsonl" and f.suffix != ".tmp":
            out[str(f.relative_to(root))] = normalize(
                f.read_text(encoding="utf-8"))
    return out


class _FakeApi:
    """Scripted Api replacement: chat(role, msgs) pops the next response."""

    def __init__(self, p, responses, calls):
        self.p = p
        self._responses = responses
        self._calls = calls

    def chat(self, role, msgs, max_tokens=None, stream_cb=None, progress=True,
             token=None, on_retry_event=None):
        self._calls.append(("chat", role, msgs, max_tokens))
        return self._responses.pop(0), "stop", {}


def run_cli(root, name, responses, answers=(), edits=None, args=None):
    """Run one continuity/review/export command at the frozen clock.

    name:    "update-state" | "compress" | "critique" | "check" | "revise" |
             "status" | "export"
    responses: list of model outputs consumed in order (str, or Exception to
             raise from chat)
    answers: scripted input() answers consumed in order (default: accept)
    edits:   {input_kind: replacement_text} for edit_saved (no editor)
    args:    extra SimpleNamespace fields (scene, summary_only, from_id, to_id,
             replace, out)

    Returns (transcript, snapshot_dict, calls). Never touches a terminal,
    pager or external editor.
    """
    calls, responses = [], list(responses)
    answers = list(answers)
    edits = dict(edits or {})

    class Api(_FakeApi):
        def __init__(self, p):
            super().__init__(p, responses, calls)

    def fake_ask(prompt=""):
        return answers.pop(0) if answers else "a"

    def fake_edit_saved(p, kind, initial):
        assert edits or True
        text = edits.get(kind, initial)
        utils.save_input(p.root, kind, text)
        return text

    saved = {obj: getattr(utils, obj) for obj in ("now", "stamp", "ask", "edit_text", "edit_saved", "page")}
    saved_cmd = {obj: getattr(commands, obj) for obj in ("now", "stamp", "ask", "edit_saved", "Api")}
    out, err = io.StringIO(), io.StringIO()
    try:
        utils.now = lambda: NOW
        utils.stamp = lambda: STAMP
        utils.ask = fake_ask
        utils.edit_text = _forbidden("edit_text")
        utils.edit_saved = fake_edit_saved
        utils.page = lambda text: print(text)
        commands.now = utils.now
        commands.stamp = utils.stamp
        commands.ask = fake_ask
        commands.edit_saved = fake_edit_saved
        commands.Api = Api
        base_ns = dict(scene=None, summary_only=False, from_id=None,
                       to_id=None, replace=False, out=None)
        base_ns.update(args or {})
        ns = types.SimpleNamespace(**base_ns)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            from longform_core.project import Project
            Project(root).root  # validate like the CLI entry point
            cmd = {"update-state": commands.cmd_update_state,
                   "compress": commands.cmd_compress,
                   "critique": commands.cmd_critique,
                   "check": commands.cmd_check,
                   "revise": commands.cmd_revise,
                   "status": commands.cmd_status,
                   "export": commands.cmd_export}[name]
            try:
                cmd(Project(root), ns)
            except SystemExit:
                pass
    finally:
        for obj, val in saved.items():
            setattr(utils, obj, val)
        for obj, val in saved_cmd.items():
            setattr(commands, obj, val)
    transcript = out.getvalue() + err.getvalue()
    return transcript, snapshot(root), calls


def _forbidden(name):
    def boom(*_a, **_k):
        raise AssertionError(f"terminal/editor helper {name} must not run in tests")
    return boom
