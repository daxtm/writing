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
from .utils import col, die, now, warn

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

    def get(self, path, token=None, on_retry_event=None):
        """GET with optional cooperative cancellation and retry events.

        `token` is checked before each attempt and interrupts retry backoff;
        `on_retry_event(why, delay)` replaces the terminal retry line. Both
        default to the unchanged CLI behavior."""
        def once():
            r = httpx.get(self.base + path, headers=self.headers, timeout=self.timeout)
            if r.status_code != 200:
                raise HttpErr(r.status_code, r.text)
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

    def _post(self, url, body, stream_cb, kind, progress=None, thinking=False, token=None):
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

    def chat(self, role, messages, max_tokens=None, stream_cb=None, progress=True,
             token=None, on_retry_event=None):
        """Returns (answer, finish_reason, usage). Thinking never reaches the answer: it is split off
        by the reasoning field or </think>, and an unfinished thought raises NoAnswerErr.

        `token` adds cooperative cancellation checks around the request;
        `on_retry_event(why, delay)` replaces the terminal retry line. Both
        default to the unchanged CLI behavior."""
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
            retry_cb = lambda why, delay: on_retry_event(why, delay)
        else:
            retry_cb = self._on_retry
        try:
            content, finish, usage, reasoning, bad = self._retry(
                lambda: self._post(self.base + "/chat/completions", body, stream_cb, "chat", prog, thinking_on, token=token),
                retry_cb, token=token)
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

    def complete(self, role, prompt, params, extra=None, stream_cb=None, meta=None,
                 token=None, on_retry_event=None):
        """Text completion. `extra` holds params Featherless doesn't document (DRY); if the
        server rejects them they are dropped for the rest of the session, with a warning.

        `token` adds cooperative cancellation checks before each attempt and at
        stream chunks; `on_retry_event` (used by the GUI) is called before a
        retry so a streamed preview can reset instead of concatenating failed
        attempt fragments. Both default to the unchanged CLI behavior."""
        rc = self.p.cfg["roles"][role]
        body = {"model": rc["model"], "prompt": prompt, **params}
        sent_extra = bool(extra) and self.extra_ok
        if sent_extra:
            body.update(extra)
        url = self.base + "/completions"
        t0 = time.time()

        def attempt(tok=None):
            return self._post(url, body, stream_cb, "text", token=tok)

        def retriable(fn):
            if on_retry_event is not None:
                # GUI: a retried stream attempt resets the preview instead of
                # concatenating failed-attempt fragments with the response.
                return self._retry(fn, lambda why, delay: on_retry_event("reset"), token=token)
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
                text, finish, usage, _, bad = retriable(attempt)
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
                    why = f"{type(e).__name__}: {e}"
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

