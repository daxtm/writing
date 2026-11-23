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
    "api_base": BASE,
    "request_timeout_s": 10,
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


def make_api(mock_http, handler, p=None):
    mock_http(handler)
    return longform.Api(p or FakeP())


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
