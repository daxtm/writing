"""Deterministic cancellation/stale tests for shared draft operations (task 1.3).

Headless (no Qt): barriers at request/chunk/save/settlement boundaries with a
fake provider and MockTransport streams. Qt worker button flows live in
tests/qt_widget_cases.py.
"""

import json
import threading
import time
from pathlib import Path

import httpx
import pytest

from longform_core import draft_operations as dop
from longform_core.api import Api, HttpErr
from longform_core.cancel import Cancelled, CancellationToken

from tests.test_draft_parity import BATCH_A, build  # shared synthetic project

BASE = "https://api.example.invalid/v1"


class GatedProvider:
    """Provider seam with deterministic chunk/save barriers."""

    def __init__(self, chunks=("A ", "B ", "C.")):
        self.chunks = list(chunks)
        self.calls = []
        self.chunk_gate = None        # threading.Event: block before chunk k
        self.gate_chunk = 1
        self.save_gate = None         # threading.Event: block after streaming
        self.starts = 0

    def complete(self, role, prompt, params, extra=None, stream_cb=None,
                 meta=None, token=None, **kw):
        self.calls.append({"prompt": prompt, "params": dict(params)})
        self.starts += 1
        out = []
        for i, ch in enumerate(self.chunks):
            if self.chunk_gate is not None and i == self.gate_chunk and \
                    not self.chunk_gate.wait(10):
                raise AssertionError("chunk gate never opened")
            if token is not None:
                token.check()
            out.append(ch)
            if stream_cb:
                stream_cb(ch)
        if self.save_gate is not None and not self.save_gate.wait(10):
            raise AssertionError("save gate never opened")
        return "".join(out), "stop", {}

    def many(self, fn, n, token=None, on_event=None):
        return [fn() for _ in range(n)]


def tree_of(root):
    return json.loads((Path(root) / "trees" / "s001.json").read_text(encoding="utf-8"))


def test_cancelled_before_request_makes_no_call_and_saves_nothing(tmp_path):
    root = build(tmp_path / "p")
    prov = GatedProvider()
    token = CancellationToken()
    token.cancel()
    with pytest.raises(Cancelled):
        dop.generate_candidates(root, "s001", count=1, provider_factory=lambda p: prov,
                                token=token)
    assert prov.calls == [] and prov.starts == 0
    t = tree_of(root)
    assert set(t["nodes"]) == {"n1"} and t["head"] == "n1"


def test_cancel_during_stream_aborts_at_chunk_and_saves_nothing(tmp_path):
    root = build(tmp_path / "p")
    prov = GatedProvider()
    token = CancellationToken()
    result = {}

    def run():
        try:
            dop.generate_candidates(root, "s001", count=1,
                                    provider_factory=lambda p: prov, token=token)
        except Cancelled as e:
            result["err"] = e

    prov.chunk_gate = threading.Event()
    th = threading.Thread(target=run)
    th.start()
    deadline = time.time() + 10
    while prov.starts < 1 and time.time() < deadline:
        time.sleep(0.005)
    token.cancel()          # Stop while the fake provider is blocked
    prov.chunk_gate.set()
    th.join(10)
    assert isinstance(result.get("err"), Cancelled), "cancel is a distinct result"
    t = tree_of(root)
    assert set(t["nodes"]) == {"n1"} and t["head"] == "n1", "no partial node on cancel"


def test_cancel_before_save_discards_the_response(tmp_path):
    root = build(tmp_path / "p")
    prov = GatedProvider()
    token = CancellationToken()

    def run():
        try:
            dop.generate_candidates(root, "s001", count=1,
                                    provider_factory=lambda p: prov, token=token)
        except Cancelled:
            pass

    prov.save_gate = threading.Event()
    th = threading.Thread(target=run)
    th.start()
    deadline = time.time() + 10
    while prov.starts < 1 and time.time() < deadline:
        time.sleep(0.005)
    token.cancel()          # Stop reaches the save boundary
    prov.save_gate.set()
    th.join(10)
    t = tree_of(root)
    assert set(t["nodes"]) == {"n1"} and t["head"] == "n1", \
        "a save refused by cancellation commits nothing"


def test_stale_source_change_refuses_the_save(tmp_path):
    root = build(tmp_path / "p")
    prov = GatedProvider()
    events = []
    result = {}

    def run():
        try:
            dop.generate_candidates(root, "s001", count=1,
                                    provider_factory=lambda p: prov,
                                    events=events.append)
        except dop.OpError as e:
            result["err"] = e

    prov.chunk_gate = threading.Event()
    th = threading.Thread(target=run)
    th.start()
    deadline = time.time() + 10
    while prov.starts < 1 and time.time() < deadline:
        time.sleep(0.005)
    # an external change while the request runs (as another writer would do)
    t = tree_of(root)
    t["nodes"]["n9"] = {"id": "n9", "parent": "n1", "text": "external",
                        "created": "x", "history": [], "sep": "\n\n"}
    (root / "trees" / "s001.json").write_text(json.dumps(t), encoding="utf-8")
    prov.chunk_gate.set()
    th.join(10)
    err = result.get("err")
    assert isinstance(err, dop.OpError) and err.stale, "stale write refused"
    assert "trees/s001.json" in str(err)
    assert tree_of(root)["nodes"]["n9"]["text"] == "external", \
        "the external change is preserved, never overwritten"


def test_api_token_interrupts_retry_backoff(tmp_path, mock_http):
    """Stop during retry backoff wakes the wait; no new request is sent."""
    root = build(tmp_path / "p")
    calls = []
    gate = threading.Event()

    def handler(request):
        calls.append(request.url.path)
        gate.wait(10)
        return httpx.Response(503, text="unavailable")

    mock_http(handler)
    token = CancellationToken()
    result = {}

    def run():
        try:
            Api(__import__("longform_core.project", fromlist=["Project"]).Project(root)).complete(
                "writer", "prompt", {"max_tokens": 5}, token=token)
        except Cancelled as e:
            result["err"] = e

    th = threading.Thread(target=run)
    th.start()
    deadline = time.time() + 10
    while not calls and time.time() < deadline:
        time.sleep(0.005)
    t0 = time.time()
    token.cancel()          # interrupt the 2s backoff immediately
    gate.set()
    th.join(10)
    assert isinstance(result.get("err"), Cancelled)
    assert time.time() - t0 < 1.5, "backoff wait is interruptible"
    assert len(calls) == 1, "no new request/retry after Stop"


def test_api_token_aborts_a_blocked_stream(tmp_path, mock_http):
    """A blocked stream read observes the token; the request is not retried."""
    root = build(tmp_path / "p")
    opened = []
    gate = threading.Event()

    def handler(request):
        opened.append(1)
        gate.wait(10)
        return httpx.Response(503, text="x")

    mock_http(handler)
    token = CancellationToken()
    result = {}

    def run():
        try:
            Api(__import__("longform_core.project", fromlist=["Project"]).Project(root)).complete(
                "writer", "prompt", {"max_tokens": 5}, token=token)
        except Cancelled as e:
            result["err"] = e

    th = threading.Thread(target=run)
    th.start()
    deadline = time.time() + 10
    while not opened and time.time() < deadline:
        time.sleep(0.005)
    token.cancel()
    gate.set()
    th.join(10)
    assert isinstance(result.get("err"), Cancelled)
    assert len(opened) == 1


def test_api_many_never_swallows_cancellation(tmp_path):
    """Cancelled futures are a distinct Stop result, not candidate failures."""
    proj = build(tmp_path / "p")
    p = __import__("longform_core.project", fromlist=["Project"]).Project(proj)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(Cancelled):
        Api(p).many(lambda: "x", 2, token=token)

    token2 = CancellationToken()
    failures = []

    def flaky():
        token2.check()
        return "y"

    token2.cancel()
    events = []
    with pytest.raises(Cancelled):
        Api(p).many(flaky, 2, token=token2, on_event=events.append)
    assert all(e.get("type") != "candidate_failed" for e in events)


def test_repeated_stop_is_safe_and_shortfall_reported(tmp_path):
    root = build(tmp_path / "p")
    prov = GatedProvider()
    token = CancellationToken()
    token.cancel()
    token.cancel()          # repeated Stop is idempotent
    with pytest.raises(Cancelled):
        dop.generate_candidates(root, "s001", count=3,
                                provider_factory=lambda p: prov, token=token)
    assert prov.starts == 0

    class Partial:
        def complete(self, *a, **k):
            return "ONLY ONE. ", "stop", {}

        def many(self, fn, n, token=None, on_event=None, indexed=None):
            return [("ONLY ONE. ", "stop", {})]

    events = []
    res = dop.generate_candidates(root, "s001", count=3, steer="",
                                  provider_factory=lambda p: Partial(),
                                  events=events.append)
    assert res.saved and res.shortfall == 2
    assert {"type": "shortfall", "got": 1, "wanted": 3} in events
    t = tree_of(root)
    assert t["head"] == "n1", "generation never moves the head"


class PausedBatchProvider:
    """Two-slot batch: slot 0 completes quietly, slot 1 streams one preview
    fragment and blocks on the shared gate; the token check lands after the
    gate, so Stop cannot fabricate a completion for the paused candidate."""

    def __init__(self, fail=False):
        self.fail = fail
        self.gate = threading.Event()
        self.started = 0

    def complete(self, role, prompt, params, extra=None, stream_cb=None,
                 meta=None, token=None, preview_events=None, **kw):
        i = self.started
        self.started += 1
        if i == 0:
            return "DONE ONE. ", "stop", {}
        if preview_events is not None:
            preview_events({"type": "preview_start", "attempt_id": 1})
            preview_events({"type": "preview_delta", "attempt_id": 1,
                            "text": "FRAG "})
        if self.gate is not None and not self.gate.wait(10):
            raise AssertionError("gate never opened")
        if token is not None:
            token.check()
        if self.fail:
            raise HttpErr(500, "boom")
        return "NEVER. ", "stop", {}

    def many(self, fn, n, token=None, on_event=None, indexed=None):
        import concurrent.futures as cf
        results, cancelled = [], False
        with cf.ThreadPoolExecutor(max_workers=max(1, n)) as ex:
            futs = [ex.submit(indexed(i) if indexed is not None else fn)
                    for i in range(n)]
            for i, fut in enumerate(futs):
                try:
                    results.append(fut.result())
                except Cancelled:
                    cancelled = True
                except Exception as e:  # noqa: BLE001 (mirrors Api.many)
                    if on_event:
                        on_event({"type": "candidate_failed", "k": i + 1,
                                  "n": n,
                                  "msg": f"candidate {i + 1}/{n} failed: "
                                         f"{type(e).__name__}: {e}"})
        if cancelled:
            raise Cancelled("stopped")
        return results


def test_stop_paused_batch_keeps_committed_work_and_saves_no_fragment(tmp_path):
    """Task 1.7: Stop while one candidate is paused after provisional text
    keeps the previously committed complete work, saves no fragment, and the
    paused candidate's preview never gains a fabricated completion."""
    root = build(tmp_path / "p")
    seed = dop.generate_candidates(root, "s001", count=1, steer="",
                                   provider_factory=lambda p: GatedProvider())
    assert seed.saved == ["n2"], "a complete candidate from an earlier batch"
    prov = PausedBatchProvider()
    evs = []
    token = CancellationToken()
    result = {}

    def run():
        try:
            dop.generate_candidates(root, "s001", count=2, steer="",
                                    provider_factory=lambda p: prov,
                                    token=token, events=evs.append,
                                    preview_events=lambda i: (
                                        lambda e: evs.append(e)))
        except Cancelled as e:
            result["err"] = e

    th = threading.Thread(target=run)
    th.start()
    deadline = time.time() + 10
    while prov.started < 2 and time.time() < deadline:
        time.sleep(0.005)
    token.cancel()              # Stop while the second candidate is paused
    prov.gate.set()
    th.join(10)
    assert isinstance(result.get("err"), Cancelled), "Stop is a distinct result"
    t = tree_of(root)
    assert set(t["nodes"]) == {"n1", "n2"} and t["head"] == "n1", \
        "committed complete work survives; no fragment node is saved"
    frag = [e for e in evs if e.get("type", "").startswith("preview_")]
    assert any(e.get("text") == "FRAG " for e in frag), \
        "the provisional fragment streamed before Stop"
    assert not any(e["type"] == "preview_complete" for e in frag), \
        "a stopped candidate never completes"
    assert frag[-1]["type"] == "preview_delta", \
        "the paused candidate's stream stops at its last delta"


def test_failed_batch_with_previews_reports_and_keeps_complete_candidate(tmp_path):
    """A paused candidate that fails after provisional text: the complete
    candidate is saved, the failure is reported, no fragment is saved or
    completed, and head/committed files are unchanged."""
    root = build(tmp_path / "p")
    prov = PausedBatchProvider(fail=True)
    prov.gate = None          # the failing candidate fails after its fragment
    evs = []
    res = dop.generate_candidates(root, "s001", count=2, steer="",
                                  provider_factory=lambda p: prov,
                                  events=evs.append,
                                  preview_events=lambda i: (
                                      lambda e: evs.append(e)))
    assert res.saved == ["n2"] and res.shortfall == 1
    assert {"type": "candidate_failed", "k": 2, "n": 2} in \
        [{k: e.get(k) for k in ("type", "k", "n")} for e in evs], \
        "the failed candidate is reported on the events channel"
    frag = [e for e in evs if e.get("type", "").startswith("preview_")]
    assert any(e.get("text") == "FRAG " for e in frag)
    assert not any(e["type"] == "preview_complete"
                   for e in frag), "a failed candidate never completes"
    t = tree_of(root)
    assert set(t["nodes"]) == {"n1", "n2"} and t["head"] == "n1", \
        "the complete candidate is saved with existing semantics; no fragment"
