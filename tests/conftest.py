"""Offline test environment for longform.py.

Imports the single-file CLI directly (no package install), strips real
credentials, and fails closed on any real network access -- in-process and in
subprocesses (checker/CLI runs) via a temporary sitecustomize.py on PYTHONPATH.
"""

import os
import socket
import sys
import textwrap
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import longform  # noqa: E402

CREDENTIAL_VARS = ("FEATHERLESS_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")


def _refuse(*_args, **_kwargs):
    raise AssertionError("real network access attempted during tests")


@pytest.fixture(autouse=True)
def offline_guards(monkeypatch):
    """No credentials, no sockets, no real httpx transport in any test."""
    for name in CREDENTIAL_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refuse)
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


@pytest.fixture
def net_guard_env(tmp_path):
    """Environment for CLI/checker subprocesses: sockets fail closed there too."""
    guard_dir = tmp_path / "netguard"
    guard_dir.mkdir()
    (guard_dir / "sitecustomize.py").write_text(textwrap.dedent("""
        import socket

        def _refuse(*_a, **_k):
            raise AssertionError("network access attempted in a test subprocess")

        socket.socket.connect = _refuse
        socket.create_connection = _refuse
    """))
    env = dict(os.environ)
    env["PYTHONPATH"] = str(guard_dir)
    for name in CREDENTIAL_VARS:
        env.pop(name, None)
    return env


@pytest.fixture
def mock_http(monkeypatch):
    """Delegate longform's module-level httpx.get/stream to a MockTransport client.

    Usage: client = mock_http(handler)  -- handler(request) -> httpx.Response.
    Returns the client; every (method, url) is appended to mock_http.calls.
    """
    calls = []

    def install(handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))

        def fake_get(url, **kwargs):
            calls.append(("GET", url))
            return client.get(url, **kwargs)

        def fake_stream(method, url, **kwargs):
            calls.append((method, url))
            return client.stream(method, url, **kwargs)

        monkeypatch.setattr(longform.httpx, "get", fake_get)
        monkeypatch.setattr(longform.httpx, "stream", fake_stream)
        return client

    install.calls = calls
    return install
