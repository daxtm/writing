"""Tests for Api: GET/retries, chat/text request bodies and SSE parsing, via MockTransport.

Real credentials are removed by conftest; every allowed request goes through a
MockTransport handler that rejects unexpected (method, url) combinations, and the
autouse guard fails any request that escapes the mocks.
"""

import json
from pathlib import Path

import httpx
import pytest

import longform

BASE = "https://api.example.invalid/v1"

ROLES = {
    "chatrole": {"model": "chat-model", "temperature": 0.5, "max_tokens": 100,
                 "thinking": True, "thinking_budget": 50},
    "quietrole": {"model": "chat-model", "temperature": 0.5, "max_tokens": 100, "thinking": False},
    "writer": {"model": "writer-model"},
}

CFG = {
    "api_key": "test-key-123",
    "api_key_env": "FEATHERLESS_API_KEY",
    "api_base": BASE,
    "request_timeout_s": 10,
    "max_parallel": 2,
    "roles": ROLES,
}


class FakeP:
    def __init__(self, cfg=None):
        self.cfg = cfg or json.loads(json.dumps(CFG))
        self.calib = []
        self.logs = []

    def f(self, *parts):
        return Path("fakeproj").joinpath(*parts)

    def record_calib(self, model, chars, tokens):
        self.calib.append((model, chars, tokens))

    def log_call(self, rec):
        self.logs.append(rec)


def sse(*chunks):
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())


def delta_chunk(delta=None, finish=None, usage=None):
    ch = {}
    if delta is not None:
        ch["delta"] = delta
    if finish is not None:
        ch["finish_reason"] = finish
    out = {"choices": [ch] if ch else []}
    if usage is not None:
        out["usage"] = usage
    return out


def text_chunk(text, finish=None, usage=None):
    ch = {"text": text}
    if finish is not None:
        ch["finish_reason"] = finish
    out = {"choices": [ch]}
    if usage is not None:
        out["usage"] = usage
    return out


def json_response(payload, status=200):
    return httpx.Response(status, json=payload)


@pytest.fixture
def api_env(monkeypatch):
    """Recorded no-op sleeps and captured warnings; returns (sleeps, warns)."""
    sleeps, warns = [], []
    monkeypatch.setattr(longform.time, "sleep", lambda s: sleeps.append(s))
    # warn moved to the api module in the package split; patch it at its call site.
    monkeypatch.setattr(longform.api, "warn", warns.append)
    return sleeps, warns


def bodies(calls):
    """bodies recorded by handlers, appended as (method, path, json_body_or_None)."""
    return calls


def make_api(mock_http, handler, p=None, session_key=None):
    mock_http(handler)
    return longform.Api(p or FakeP(), session_key=session_key)


# --------------------------------------------------------------------------- GET and retries


def test_get_success(mock_http):
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.headers["Authorization"]))
        if request.method == "GET" and request.url.path == "/v1/plan":
            return json_response({"plan": True})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    api = make_api(mock_http, handler)
    assert api.get("/plan") == {"plan": True}
    assert seen == [("GET", "/v1/plan", "Bearer test-key-123")]
    assert mock_http.calls == [("GET", BASE + "/plan")]
    assert api.p.logs == []


def test_get_error_not_retried(mock_http, api_env):
    sleeps, _ = api_env

    def handler(request):
        return json_response({"error": "nope"}, status=404)

    api = make_api(mock_http, handler)
    with pytest.raises(longform.HttpErr) as e:
        api.get("/plan")
    assert e.value.status == 404
    assert sleeps == [] and len(mock_http.calls) == 1


def test_retry_status_exhaustion(mock_http, api_env):
    sleeps, _ = api_env
    hits = []

    def handler(request):
        hits.append(request)
        return json_response({"error": "busy"}, status=429)

    api = make_api(mock_http, handler)
    with pytest.raises(longform.HttpErr) as e:
        api.get("/plan")
    assert e.value.status == 429
    assert len(hits) == 7
    assert sleeps == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0]


def test_transport_error_exhaustion(mock_http, api_env):
    sleeps, _ = api_env

    def handler(request):
        raise httpx.ConnectError("simulated outage", request=request)

    api = make_api(mock_http, handler)
    with pytest.raises(httpx.ConnectError):
        api.get("/plan")
    assert len(mock_http.calls) == 7
    assert sleeps == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0]


def test_retry_then_success(mock_http, api_env):
    sleeps, _ = api_env
    n = 0

    def handler(request):
        nonlocal n
        n += 1
        if n == 1:
            return json_response({"error": "unavailable"}, status=503)
        return json_response({"ok": 1})

    api = make_api(mock_http, handler)
    assert api.get("/plan") == {"ok": 1}
    assert n == 2 and sleeps == [2.0]


# --------------------------------------------------------------------------- chat


def test_chat_request_body_and_result(mock_http):
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, json.loads(request.content)))
        if request.method == "POST" and request.url.path == "/v1/chat/completions":
            return sse(
                delta_chunk({"reasoning_content": "let me think"}, ),
                delta_chunk({"content": "Hello"}),
                delta_chunk({"content": " world"}, finish="stop", usage={"prompt_tokens": 10, "completion_tokens": 2}),
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    api = make_api(mock_http, handler)
    msgs = [{"role": "user", "content": "hi"}]
    answer, finish, usage = api.chat("chatrole", msgs, progress=False)
    assert answer == "Hello world" and finish == "stop" and usage == {"prompt_tokens": 10, "completion_tokens": 2}
    method, path, body = seen[0]
    assert (method, path) == ("POST", "/v1/chat/completions")
    assert body["model"] == "chat-model"
    assert body["messages"] == msgs
    assert body["temperature"] == 0.5 and body["max_tokens"] == 100
    assert body["stream"] is True
    assert body["chat_template_kwargs"] == {"enable_thinking": True, "thinking_budget": 50}
    assert mock_http.calls == [("POST", BASE + "/chat/completions")]
    assert api.p.calib == [("chat-model", 2, 10)]
    rec = api.p.logs[0]
    assert rec["endpoint"] == "chat" and rec["output"] == "Hello world" and rec["usage"] == usage


def test_chat_optional_samplers_and_no_thinking(mock_http):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return sse(delta_chunk({"content": "ok"}, finish="stop", usage={"prompt_tokens": 3}))

    api = make_api(mock_http, handler)
    answer, _, _ = api.chat("quietrole", [{"role": "user", "content": "hey"}], max_tokens=9, progress=False)
    assert answer == "ok"
    body = seen[0]
    assert body["max_tokens"] == 9
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "top_p" not in body


def test_chat_split_inline_thinking(mock_http):
    def handler(request):
        return sse(delta_chunk({"content": "thinking hard</think>Final answer"}),
                   delta_chunk({}, finish="stop", usage={"prompt_tokens": 5}))

    api = make_api(mock_http, handler)
    answer, finish, _ = api.chat("chatrole", [{"role": "user", "content": "q"}], progress=False)
    assert answer == "Final answer"
    assert "thinking hard" in api.p.logs[0]["thinking"]


def test_chat_no_answer_when_still_thinking(mock_http):
    def handler(request):
        return sse(delta_chunk({"content": "																					"}),
                   delta_chunk({}, finish="length"))

    api = make_api(mock_http, handler)
    with pytest.raises(longform.NoAnswerErr) as e:
        api.chat("chatrole", [{"role": "user", "content": "q"}], progress=False)
    assert "still thinking" in str(e.value)


def test_chat_empty_answer_error(mock_http):
    def handler(request):
        return sse(delta_chunk({}, finish="stop", usage={"prompt_tokens": 1}))

    api = make_api(mock_http, handler)
    with pytest.raises(longform.NoAnswerErr) as e:
        api.chat("quietrole", [{"role": "user", "content": "q"}], progress=False)
    assert "empty answer" in str(e.value)


def test_chat_malformed_chunks_and_missing_finish(mock_http, api_env):
    _, warns = api_env

    def handler(request):
        body = (b"data: not json\n\n"
                + f"data: {json.dumps(delta_chunk({'content': 'partial'}))}\n\n".encode()
                + f"data: {json.dumps({'usage': {'prompt_tokens': 4}})}\n\n".encode())
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    api = make_api(mock_http, handler)
    answer, finish, usage = api.chat("quietrole", [{"role": "user", "content": "q"}], progress=False)
    assert answer == "partial" and finish is None and usage == {"prompt_tokens": 4}
    rec = api.p.logs[0]
    assert rec["bad_chunks"] == ["not json"]
    assert any("malformed chunk" in n for n in rec["stream_problems"])
    assert any("without a finish reason" in n for n in rec["stream_problems"])
    assert warns, "stream problems must be warned"


def test_chat_reasoning_field_and_done_marker(mock_http):
    def handler(request):
        body = (f"data: {json.dumps(delta_chunk({'reasoning': 'thoughts'}))}\n\n".encode()
                + f"data: {json.dumps(delta_chunk({'content': 'answer'}))}\n\n".encode()
                + b"data: [DONE]\n\n")
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    api = make_api(mock_http, handler)
    answer, finish, _ = api.chat("chatrole", [{"role": "user", "content": "q"}], progress=False)
    assert answer == "answer" and finish is None
    assert "thoughts" in api.p.logs[0]["thinking"]


# --------------------------------------------------------------------------- text completion


def test_complete_body_with_extra(mock_http):
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, json.loads(request.content)))
        return sse(text_chunk("Once upon", finish="stop", usage={"prompt_tokens": 7, "completion_tokens": 3}))

    api = make_api(mock_http, handler)
    text, finish, usage = api.complete("writer", "PROMPT", {"temperature": 1.0, "max_tokens": 50},
                                       extra={"dry_multiplier": 0.8}, meta={"k": 1})
    assert text == "Once upon" and finish == "stop"
    method, path, body = seen[0]
    assert (method, path) == ("POST", "/v1/completions")
    assert body["model"] == "writer-model" and body["prompt"] == "PROMPT"
    assert body["dry_multiplier"] == 0.8 and body["stream"] is True
    assert api.p.calib == [("writer-model", 6, 7)]
    rec = api.p.logs[0]
    assert rec["endpoint"] == "completions" and rec["extra_sent"] is True
    assert rec["extra"] == {"dry_multiplier": 0.8} and rec["meta"] == {"k": 1}


def test_complete_rejected_extra_fallback(mock_http, api_env):
    _, warns = api_env
    bodies_seen = []

    def handler(request):
        body = json.loads(request.content)
        bodies_seen.append(body)
        if "dry_multiplier" in body:
            return json_response({"error": {"message": "unknown parameter dry_multiplier is not supported"}},
                                 status=400)
        return sse(text_chunk("clean text", finish="stop", usage={"prompt_tokens": 6}))

    api = make_api(mock_http, handler)
    text, finish, _ = api.complete("writer", "PROMPT", {"max_tokens": 50}, extra={"dry_multiplier": 0.8})
    assert text == "clean text" and finish == "stop"
    assert len(bodies_seen) == 2
    assert "dry_multiplier" in bodies_seen[0] and "dry_multiplier" not in bodies_seen[1]
    assert api.extra_ok is False
    assert any("rejected" in w for w in warns)
    assert api.p.logs[0]["extra_sent"] is False
    assert len(mock_http.calls) == 2


def test_complete_non_extra_400_propagates(mock_http, api_env):
    def handler(request):
        return json_response({"error": "bad request"}, status=400)

    api = make_api(mock_http, handler)
    with pytest.raises(longform.HttpErr):
        api.complete("writer", "PROMPT", {})
    assert api.extra_ok is True and len(mock_http.calls) == 1


# --------------------------------------------------------------------------- fail-closed network


def test_unexpected_real_network_is_blocked():
    with pytest.raises(AssertionError, match="real network access"):
        httpx.get("https://api.example.invalid/v1/plan")


# ------------------------------------------------------- session credential (ADR-0011)


def test_session_override_wins_over_project_and_environment(mock_http, monkeypatch):
    monkeypatch.setenv("FEATHERLESS_API_KEY", "env-sentinel-2")
    seen = []

    def handler(request):
        seen.append(request.headers["Authorization"])
        return json_response({"plan": True})

    api = make_api(mock_http, handler, session_key="  session-sentinel-1  ")
    api.get("/plan")
    assert seen == ["Bearer session-sentinel-1"], \
        "session > project > environment; the value is trimmed"
    assert api.cred_source == "session"
    assert api.session_key == "session-sentinel-1"
    assert set(api.secrets) == {"session-sentinel-1", "test-key-123",
                                "env-sentinel-2"}, \
        "redaction covers every nonempty source, not only the winner"
    assert mock_http.calls == [("GET", BASE + "/plan")]


def test_no_override_prefers_project_then_environment(mock_http, monkeypatch):
    monkeypatch.setenv("FEATHERLESS_API_KEY", "env-sentinel-2")
    seen = []

    def handler(request):
        seen.append(request.headers["Authorization"])
        return json_response({"plan": True})

    api = make_api(mock_http, handler)          # project key wins over env
    api.get("/plan")
    assert seen == ["Bearer test-key-123"]
    assert api.cred_source == "project"

    cfg = json.loads(json.dumps(CFG))
    cfg["api_key"] = ""
    api2 = make_api(mock_http, handler, FakeP(cfg))   # environment fallback
    api2.get("/plan")
    assert seen[-1] == "Bearer env-sentinel-2"
    assert api2.cred_source == "environment"
    assert "env-sentinel-2" in api2.secrets and "test-key-123" not in api2.secrets


def test_empty_session_key_keeps_no_override_behavior(mock_http):
    seen = []

    def handler(request):
        seen.append(request.headers["Authorization"])
        return json_response({"plan": True})

    api = make_api(mock_http, handler, session_key="   ")
    api.get("/plan")
    assert seen == ["Bearer test-key-123"]
    assert api.session_key is None and api.cred_source == "project"


def test_no_override_missing_key_dies_unchanged(mock_http, monkeypatch):
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    cfg = json.loads(json.dumps(CFG))
    cfg["api_key"] = ""
    mock_http(lambda request: json_response({}))
    with pytest.raises(SystemExit) as e:
        longform.Api(FakeP(cfg))
    assert "no API key" in getattr(e.value, "msg", "")


def test_no_override_invalid_env_name_dies_unchanged(mock_http):
    cfg = json.loads(json.dumps(CFG))
    cfg["api_key"] = ""
    cfg["api_key_env"] = "sk-not-a-name"
    mock_http(lambda request: json_response({}))
    with pytest.raises(SystemExit) as e:
        longform.Api(FakeP(cfg))
    assert "must be the NAME" in getattr(e.value, "msg", "")


def test_session_override_never_dies_on_missing_disk_credentials(mock_http):
    cfg = json.loads(json.dumps(CFG))
    cfg["api_key"] = ""
    cfg["api_key_env"] = "FEATHERLESS_API_KEY"
    seen = []

    def handler(request):
        seen.append(request.headers["Authorization"])
        return json_response({"plan": True})

    api = make_api(mock_http, handler, FakeP(cfg), session_key="sess")
    api.get("/plan")
    assert seen == ["Bearer sess"]


def test_http_error_body_echoing_credentials_is_redacted(mock_http, monkeypatch):
    monkeypatch.setenv("FEATHERLESS_API_KEY", "env-sentinel-2")

    def handler(request):
        return json_response(
            {"error": "bad key test-key-123 / env-sentinel-2"}, status=403)

    api = make_api(mock_http, handler, session_key="session-sentinel-1")
    with pytest.raises(longform.HttpErr) as e:
        api.get("/plan")
    msg = str(e.value)
    assert "[redacted]" in msg
    for s in ("session-sentinel-1", "test-key-123", "env-sentinel-2"):
        assert s not in msg


def test_chat_log_and_result_echoes_are_redacted(mock_http):
    def handler(request):
        return sse(delta_chunk({"content": "key echo test-key-123 mid"},
                               finish="stop", usage={"prompt_tokens": 3}))

    api = make_api(mock_http, handler, session_key="session-sentinel-1")
    answer, _, _ = api.chat("quietrole", [{"role": "user", "content": "q"}],
                            progress=False)
    assert answer == "key echo [redacted] mid"
    rec = api.p.logs[0]
    blob = json.dumps(rec)
    assert "test-key-123" not in blob and "session-sentinel-1" not in blob
    assert rec["output"] == "key echo [redacted] mid"


def test_streamed_split_secret_is_never_emitted(mock_http):
    def handler(request):
        return sse(text_chunk("before test-key-"),
                   text_chunk("123 after", finish="stop",
                              usage={"prompt_tokens": 2}))

    api = make_api(mock_http, handler)   # project credential sk-test... wait
    got = []
    text, _, _ = api.complete("writer", "PROMPT", {}, stream_cb=got.append)
    joined = "".join(got)
    assert "test-key-123" not in joined, "a split secret never reaches the callback"
    assert "before " in joined and " after" in joined
    assert "test-key-123" not in text
    assert "[redacted]" in text
    blob = json.dumps(api.p.logs[0])
    assert "test-key-123" not in blob


def test_candidate_failure_echo_is_redacted(mock_http):
    def handler(request):
        raise httpx.ConnectError("boom test-key-123", request=request)

    api = make_api(mock_http, handler)
    events = []

    def fn():
        raise RuntimeError("echoed test-key-123 inside failure")

    out = api.many(fn, 1, on_event=events.append)
    assert out == []
    why = events[0]["why"]
    assert "test-key-123" not in why and "[redacted]" in why
    assert api.p.logs[0]["candidate_failed"] == why


# ------------------------------------------------------- preview events (ADR-0012)


def _deltas(evs):
    return "".join(e.get("text", "") for e in evs if e["type"] == "preview_delta")


def _kinds(evs):
    return [(e.get("type"), e.get("attempt_id")) for e in evs]


def test_preview_split_think_delimiter_shows_only_answer(mock_http):
    def handler(request):
        return sse(delta_chunk({"content": "<think> MAXIMALLY"}),
                   delta_chunk({"content": "THINKING</think>"}),
                   delta_chunk({"content": " Final answer"}, finish="stop",
                               usage={"prompt_tokens": 5}))

    api = make_api(mock_http, handler)
    evs = []
    answer, _, _ = api.chat("chatrole", [{"role": "user", "content": "q"}],
                            progress=False, preview_events=evs.append)
    assert answer == "Final answer", "completed parsing is unchanged"
    assert _kinds(evs)[0] == ("preview_start", 1)
    assert _kinds(evs)[-1] == ("preview_complete", 1)
    assert _deltas(evs) == " Final answer", \
        "only answer bytes are shown, after the split delimiter completes"
    for e in evs:
        assert set(e) <= {"type", "attempt_id", "text"}, \
            "no credential/config/header objects in preview events"


def test_preview_reasoning_field_then_answer(mock_http):
    def handler(request):
        return sse(delta_chunk({"reasoning_content": "hidden thoughts"}),
                   delta_chunk({"content": "The"}),
                   delta_chunk({"content": " answer"}, finish="stop",
                               usage={"prompt_tokens": 3}))

    api = make_api(mock_http, handler)
    evs = []
    answer, _, _ = api.chat("chatrole", [{"role": "user", "content": "q"}],
                            progress=False, preview_events=evs.append)
    assert answer == "The answer"
    assert _deltas(evs) == "The answer"
    assert "hidden thoughts" not in _deltas(evs)


def test_preview_waits_through_ambiguous_implicit_prefix(mock_http):
    def handler(request):
        return sse(delta_chunk({"content": "hel"}),
                   delta_chunk({"content": "lo world"}, finish="stop",
                               usage={"prompt_tokens": 2}))

    api = make_api(mock_http, handler)
    evs = []
    answer, _, _ = api.chat("chatrole", [{"role": "user", "content": "q"}],
                            progress=False, preview_events=evs.append)
    assert answer == "hello world"
    assert _deltas(evs) == "", \
        "an undecidable prefix is withheld rather than guessed"


def test_preview_nonthinking_answer_streams_immediately(mock_http):
    def handler(request):
        return sse(delta_chunk({"content": "quick"}),
                   delta_chunk({"content": " reply"}, finish="stop",
                               usage={"prompt_tokens": 2}))

    api = make_api(mock_http, handler)
    evs = []
    answer, _, _ = api.chat("quietrole", [{"role": "user", "content": "q"}],
                            progress=False, preview_events=evs.append)
    assert answer == "quick reply"
    assert _deltas(evs) == "quick reply"


def test_preview_no_answer_never_completes(mock_http):
    def handler(request):
        return sse(delta_chunk({"content": "																					"}),
                   delta_chunk({}, finish="length"))

    api = make_api(mock_http, handler)
    evs = []
    with pytest.raises(longform.NoAnswerErr):
        api.chat("chatrole", [{"role": "user", "content": "q"}],
                 progress=False, preview_events=evs.append)
    assert _kinds(evs) == [("preview_start", 1)], \
        "waiting only: no successful complete is invented"


def test_preview_split_secret_is_redacted_in_chat(mock_http):
    def handler(request):
        return sse(delta_chunk({"content": "echo test-key-"}),
                   delta_chunk({"content": "123 tail"}, finish="stop",
                               usage={"prompt_tokens": 2}))

    api = make_api(mock_http, handler)
    evs = []
    answer, _, _ = api.chat("quietrole", [{"role": "user", "content": "q"}],
                            progress=False, preview_events=evs.append)
    assert _deltas(evs) == "echo [redacted] tail", \
        "a credential spanning chunks never reaches the preview"
    assert "test-key-123" not in _deltas(evs)


def test_preview_transport_retry_resets_attempt(mock_http, api_env):
    sleeps, _ = api_env
    n = 0

    def handler(request):
        nonlocal n
        n += 1
        if n == 1:
            return json_response({"error": "busy"}, status=503)
        return sse(delta_chunk({"content": "ok"}, finish="stop",
                               usage={"prompt_tokens": 1}))

    api = make_api(mock_http, handler)
    evs = []
    answer, _, _ = api.chat("quietrole", [{"role": "user", "content": "q"}],
                            progress=False, preview_events=evs.append)
    assert answer == "ok" and len(mock_http.calls) == 2
    assert _kinds(evs) == [("preview_start", 1), ("preview_reset", 1),
                           ("preview_start", 2), ("preview_delta", 2),
                           ("preview_complete", 2)]


def test_preview_extra_parameter_fallback_resets_attempt(mock_http):
    bodies_seen = []

    def handler(request):
        body = json.loads(request.content)
        bodies_seen.append(body)
        if "dry_multiplier" in body:
            return json_response(
                {"error": {"message": "unknown parameter dry_multiplier"}},
                status=400)
        return sse(text_chunk("clean", finish="stop",
                              usage={"prompt_tokens": 1}))

    api = make_api(mock_http, handler)
    evs = []
    text, _, _ = api.complete("writer", "PROMPT", {"max_tokens": 5},
                              extra={"dry_multiplier": 0.8},
                              preview_events=evs.append)
    assert text == "clean" and len(bodies_seen) == 2
    assert _kinds(evs) == [("preview_start", 1), ("preview_reset", 1),
                           ("preview_start", 2), ("preview_delta", 2),
                           ("preview_complete", 2)]
    assert _deltas(evs) == "clean"
