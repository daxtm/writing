"""Featherless API client (streaming, retries, progress)."""

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from .cancel import Cancelled
from .config import LOCK, RETRY_STATUS, SAMPLING_KEYS
from .utils import col, die, now, redact_obj, redact_text, warn, StreamRedactor

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


_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


class AnswerStream:
    """Incremental answer-only splitter mirroring split_thinking (ADR-0012).

    Feed raw streamed content; returns the text newly decidable as answer.
    With thinking enabled and no distinguishable boundary yet (no reasoning
    field, no opener/closer pair) bytes stay withheld - waiting/thinking
    status - instead of guessing that hidden content is answer text. The
    completed parser stays authoritative for the final answer; this adapter
    only decides what a live preview may already show."""

    def __init__(self, thinking_on=False):
        self.on = bool(thinking_on)
        self.acc = ""
        self.reasoning = False
        self.open = False
        self.closed = not self.on
        self.emitted = 0

    def note_reasoning(self):
        self.reasoning = True

    def feed(self, chunk):
        if not self.on:
            return chunk
        if not chunk:
            return ""
        self.acc += chunk
        if self.closed:
            out = self.acc[self.emitted:]
            self.emitted = len(self.acc)
            return out
        s = self.acc.lstrip()
        close = None
        for close in re.finditer(_THINK_CLOSE, self.acc, flags=re.I):
            pass
        if self.open or s[:len(_THINK_OPEN)].lower() == _THINK_OPEN:
            # inside (or entering) an inline thinking block: hold until its
            # closing tag; everything after the last close is answer
            self.open = True
            if close is None:
                return ""
            self.closed = True
            self.emitted = close.end()
            out = self.acc[self.emitted:]
            self.emitted = len(self.acc)
            return out
        if not s:
            return ""
        if close is not None:
            # a closing tag arrived without an opener at the start: content
            # before it was thinking, the remainder is answer
            self.closed = True
            self.emitted = close.end()
            out = self.acc[self.emitted:]
            self.emitted = len(self.acc)
            return out
        if self.reasoning:
            # the server separated thinking into its own field, so content
            # is the answer (same rule the completed parser applies)
            self.closed = True
            out = self.acc[self.emitted:]
            self.emitted = len(self.acc)
            return out
        return ""   # still ambiguous: hold as waiting/thinking status


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
    def __init__(self, p, session_key=None):
        """HTTP client for one project's credential chain (ADR-0011).

        The effective key is the optional window `session_key` first, then
        the project's inline `api_key`, then the configured environment
        variable — without mutating config or environment. `session_key=None`
        (or empty) keeps the unchanged no-override CLI behavior, including
        its missing-key diagnostics. Every nonempty source value is kept in
        `secrets` so echoed credentials can be redacted before logging."""
        self.p = p
        self.session_key = str(session_key or "").strip() or None
        project_key = str(p.cfg.get("api_key") or "").strip()
        env = str(p.cfg.get("api_key_env") or "")
        env_ok = bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env))
        envval = os.environ.get(env, "").strip() if env and env_ok else ""
        if self.session_key:
            key = self.session_key
        elif project_key:
            key = project_key
        elif env_ok and envval:
            key = envval
        else:
            if env and not env_ok:
                die('project.json "api_key_env" must be the NAME of an environment variable (e.g. FEATHERLESS_API_KEY), '
                    'not the key itself. Put the key in "api_key" instead.')
            die(f'no API key: set "api_key" in {p.f("project.json")}, or export {env}=...')
        self.auth_key = key
        self.cred_source = ("session" if self.session_key
                            else "project" if project_key
                            else "environment")
        self.secrets = tuple(s for s in (self.session_key, project_key, envval)
                             if s)
        self.base = p.cfg["api_base"].rstrip("/")
        self.headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        self.timeout = httpx.Timeout(float(p.cfg["request_timeout_s"]), connect=30.0)
        self.extra_ok = True

    def get(self, path, token=None, on_retry_event=None):
        """GET with optional cooperative cancellation and retry events.

        `token` is checked before each attempt and interrupts retry backoff;
        `on_retry_event(why, delay)` replaces the terminal retry line. Both
        default to the unchanged CLI behavior."""
        def once():
            r = httpx.get(self.base + path, headers=self.headers, timeout=self.timeout)
            if r.status_code != 200:
                raise HttpErr(r.status_code, redact_text(r.text, self.secrets))
            return r.json()
        if on_retry_event is not None:
            return self._retry(once, lambda why, delay: on_retry_event(why, delay),
                               token=token)
        return self._retry(once, self._on_retry, token=token)

    def _retry(self, fn, on_retry=None, token=None):
        delay = 2.0
        for attempt in range(7):
            if token:
                token.check()
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
            # Interruptible backoff: a cancelled token wakes the wait immediately.
            if token:
                token.wait(delay)
            else:
                time.sleep(delay)
            delay = min(delay * 2, 30.0)

    def _post(self, url, body, stream_cb, kind, progress=None, thinking=False, token=None,
              preview=None, rflag=None):
        """Always streams, so long generations never sit silent past the read timeout and one bad chunk
        can't sink a whole reply. kind 'chat' reads delta content (+ reasoning fields), 'text' reads choice text.
        Returns (content, finish_reason, usage, reasoning, bad_chunks).

        `preview(raw_chunk)` receives each raw content chunk for the optional
        answer-preview channel (ADR-0012); `rflag()` is called when reasoning
        field content arrives, so the preview adapter can separate them."""

        parts, rparts, bad, finish, usage = [], [], [], None, {}
        closed = False
        red = StreamRedactor(self.secrets)
        with httpx.stream("POST", url, headers=self.headers, json=dict(body, stream=True), timeout=self.timeout) as r:
            if r.status_code != 200:
                r.read()
                raise HttpErr(r.status_code, redact_text(r.text, self.secrets))
            for line in r.iter_lines():
                if token:
                    token.check()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    j = json.loads(data)
                except json.JSONDecodeError:
                    bad.append(redact_text(data, self.secrets))
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
                        if rflag:
                            rflag()
                        if progress:
                            progress("thinking", len(rr))
                t = delta.get("content") if kind == "chat" else chs[0].get("text")
                if t:
                    parts.append(t)
                    if preview:
                        preview(t)
                    if stream_cb:
                        out = red.feed(t)
                        if out:
                            stream_cb(out)
                    if progress:
                        if thinking and not closed and "</think>" in "".join(parts[-50:]).lower():
                            closed = True
                        progress("thinking" if thinking and not closed else "answer", len(t))
                if chs[0].get("finish_reason"):
                    finish = chs[0]["finish_reason"]
            # a withheld potential secret-prefix suffix is emitted (or
            # retracted) once the stream is over — never an unsafe prefix
            rest = red.flush()
            if rest and stream_cb:
                stream_cb(rest)
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

    def chat(self, role, messages, max_tokens=None, stream_cb=None, progress=True,
             token=None, on_retry_event=None, preview_events=None):
        """Returns (answer, finish_reason, usage). Thinking never reaches the answer: it is split off
        by the reasoning field or </think>, and an unfinished thought raises NoAnswerErr.

        `token` adds cooperative cancellation checks around the request;
        `on_retry_event(why, delay)` replaces the terminal retry line; the
        optional `preview_events` subscriber receives answer-only
        preview_start/delta/reset/complete events (attempt ids assigned here;
        hidden reasoning and secrets are never forwarded). All default to the
        unchanged CLI behavior."""
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
        if on_retry_event is not None:
            base_retry = lambda why, delay: on_retry_event(why, delay)
        else:
            base_retry = self._on_retry
        # Optional answer-preview channel (ADR-0012): the caller-bound closure
        # carries operation/candidate identity; this method adds attempt ids
        # and answer-only, credential-redacted text. Never raw content.
        pe = preview_events
        pstate = {"attempt": 0}

        def retry_cb(why, delay):
            if pe:
                pe({"type": "preview_reset", "attempt_id": pstate["attempt"]})
            base_retry(why, delay)

        def attempt():
            if pe:
                pstate["attempt"] += 1
                pe({"type": "preview_start", "attempt_id": pstate["attempt"]})
            stream = AnswerStream(thinking_on) if pe else None
            red = StreamRedactor(self.secrets) if pe else None

            def on_raw(t):
                out = stream.feed(t)
                if out and red:
                    out = red.feed(out)
                    if out:
                        pe({"type": "preview_delta",
                            "attempt_id": pstate["attempt"], "text": out})

            res = self._post(self.base + "/chat/completions", body, stream_cb,
                             "chat", prog, thinking_on, token=token,
                             preview=on_raw if pe else None,
                             rflag=(stream.note_reasoning if pe else None))
            if pe and red:
                rest = red.flush()
                if rest:
                    pe({"type": "preview_delta",
                        "attempt_id": pstate["attempt"], "text": rest})
            return res

        try:
            content, finish, usage, reasoning, bad = self._retry(
                attempt, retry_cb, token=token)
        finally:
            if prog:
                prog.done()
        content = redact_text(content, self.secrets)
        reasoning = redact_text(reasoning, self.secrets)
        stream_notes = self._report_stream_problems(role, finish, bad)
        answer, thought, closed = split_thinking(content, reasoning)
        if thinking_on and not reasoning and "</think>" not in content.lower() and finish == "length":
            answer, thought, closed = "", content, False  # template opened <think>; the model never closed it
        self.p.record_calib(rc["model"], sum(len(m["content"]) for m in messages), usage.get("prompt_tokens"))
        self.p.log_call(redact_obj({
            "time": now(), "role": role, "model": rc["model"], "endpoint": "chat", "seconds": round(time.time() - t0, 1),
            "params": {k: v for k, v in body.items() if k not in ("messages", "model")},
            "messages": messages, "output": answer, "thinking": thought, "raw_content": content,
            "finish_reason": finish, "usage": usage, "stream_problems": stream_notes, "bad_chunks": bad,
        }, self.secrets))
        if not answer:
            if not closed:
                raise NoAnswerErr(
                    f"{role} ({rc['model']}) was still thinking when it hit max_tokens {body.get('max_tokens', '?')}, "
                    f"so there is no answer. Raise roles.{role}.max_tokens, lower roles.{role}.thinking_budget, or set "
                    f"roles.{role}.thinking to false in {self.p.f('project.json')}.")
            raise NoAnswerErr(f"{role} ({rc['model']}) returned an empty answer (finish_reason={finish}).")
        if finish == "length":
            warn(f"{role} answer hit max_tokens {body.get('max_tokens', '?')}; it may be cut off")
        if pe:
            pe({"type": "preview_complete", "attempt_id": pstate["attempt"]})
        return answer, finish, usage

    def complete(self, role, prompt, params, extra=None, stream_cb=None, meta=None,
                 token=None, on_retry_event=None, preview_events=None):
        """Text completion. `extra` holds params Featherless doesn't document (DRY); if the
        server rejects them they are dropped for the rest of the session, with a warning.

        `token` adds cooperative cancellation checks before each attempt and at
        stream chunks; `on_retry_event` (used by the GUI) is called before a
        retry so a streamed preview can reset instead of concatenating failed
        attempt fragments; the optional `preview_events` subscriber receives
        answer-only preview_start/delta/reset/complete events (attempt ids
        assigned here, redaction applied before emission — the completion
        endpoint has no hidden reasoning). All default to the unchanged CLI
        behavior."""
        rc = self.p.cfg["roles"][role]
        body = {"model": rc["model"], "prompt": prompt, **params}
        sent_extra = bool(extra) and self.extra_ok
        if sent_extra:
            body.update(extra)
        url = self.base + "/completions"
        t0 = time.time()

        pe = preview_events
        pstate = {"attempt": 0}

        def attempt(tok=None):
            if pe:
                pstate["attempt"] += 1
                pe({"type": "preview_start", "attempt_id": pstate["attempt"]})
            red = StreamRedactor(self.secrets) if pe else None

            def on_raw(t):
                out = red.feed(t)
                if out:
                    pe({"type": "preview_delta",
                        "attempt_id": pstate["attempt"], "text": out})

            res = self._post(url, body, stream_cb, "text", token=tok,
                             preview=on_raw if pe else None)
            if pe and red:
                rest = red.flush()
                if rest:
                    pe({"type": "preview_delta",
                        "attempt_id": pstate["attempt"], "text": rest})
            return res

        def retriable(fn):
            if on_retry_event is not None or pe:
                # GUI: a retried stream attempt resets the preview instead of
                # concatenating failed-attempt fragments with the response.
                def cb(why, delay):
                    if pe:
                        pe({"type": "preview_reset",
                            "attempt_id": pstate["attempt"]})
                    if on_retry_event is not None:
                        on_retry_event("reset")
                    else:
                        self._on_retry(why, delay)
                return self._retry(fn, cb, token=token)
            return self._retry(fn, self._on_retry, token=token)

        try:
            text, finish, usage, _, bad = retriable(attempt)
        except HttpErr as e:
            if sent_extra and e.status in (400, 422) and any(k.split("_")[0] in str(e).lower() for k in extra):
                with LOCK:
                    if self.extra_ok:
                        self.extra_ok = False
                        warn("server rejected " + ", ".join(extra) + f" ({e}); sending without them for this session")
                body = {k: v for k, v in body.items() if k not in extra}
                sent_extra = False
                if pe:
                    pe({"type": "preview_reset", "attempt_id": pstate["attempt"]})
                text, finish, usage, _, bad = retriable(attempt)
            else:
                raise
        text = redact_text(text, self.secrets)
        stream_notes = self._report_stream_problems(role, finish, bad)
        self.p.record_calib(rc["model"], len(prompt), usage.get("prompt_tokens"))
        self.p.log_call(redact_obj({
            "time": now(), "role": role, "model": rc["model"], "endpoint": "completions", "seconds": round(time.time() - t0, 1),
            "params": {k: v for k, v in body.items() if k not in ("prompt", "model")},
            "extra_sent": sent_extra, "extra": extra or {}, "meta": meta or {},
            "prompt": prompt, "output": text, "finish_reason": finish, "usage": usage,
            "stream_problems": stream_notes, "bad_chunks": bad,
        }, self.secrets))
        if pe:
            pe({"type": "preview_complete", "attempt_id": pstate["attempt"]})
        return text, finish, usage

    def many(self, fn, n, token=None, on_event=None):
        """n parallel calls of fn(); completed results in completion order.

        `on_event` replaces the terminal progress prints with dicts ({"type":
        "candidate_done"/"candidate_failed", "k", "n", ...}); a cancelled token
        is never swallowed as an ordinary candidate failure."""
        workers = max(1, min(n, int(self.p.cfg["max_parallel"])))
        results = []
        if token:
            token.check()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = []
            for _ in range(n):
                if token:
                    token.check()
                futs.append(ex.submit(fn))
            was_cancelled = False
            for k, fut in enumerate(as_completed(futs), 1):
                try:
                    results.append(fut.result())
                    self._candidate_event(on_event, f"  candidate {k}/{n} done", k, n, "candidate_done", "2")
                except Cancelled:
                    was_cancelled = True
                except Exception as e:  # noqa: BLE001
                    why = f"{type(e).__name__}: {redact_text(str(e), self.secrets)}"
                    self._candidate_event(on_event, f"  candidate {k}/{n} failed: {why}", k, n,
                                          "candidate_failed", "31", why=why)
                    self.p.log_call({"time": now(), "candidate_failed": why})
            for f in futs:  # never wait on queued work after a Stop
                f.cancel()
        if was_cancelled or (token and token.cancelled):
            raise Cancelled("stopped")
        return results

    @staticmethod
    def _candidate_event(on_event, msg, k, n, kind, color, **extra):
        if on_event:
            on_event(dict({"type": kind, "k": k, "n": n, "msg": col(msg, color)}, **extra))
        else:
            print(col(msg, color), flush=True)

    def chat_many(self, role, messages, n, max_tokens=None, token=None, on_event=None):
        """n planner-style calls; optional token/on_event pass through to many()
        and each chat (defaults keep the unchanged CLI output)."""
        one_at_a_time = max(1, min(n, int(self.p.cfg["max_parallel"]))) == 1
        return self.many(
            lambda: self.chat(role, messages, max_tokens, progress=one_at_a_time, token=token),
            n, token=token, on_event=on_event)

