import json

import httpx
import pytest
import respx

from declaw import PtySize, Sandbox
from declaw.sandbox_sync.pty import PtyHandle

API_URL = "https://api.test.dev"

SANDBOX_RESP = {
    "sandbox_id": "sbx-pty",
    "template_id": "tpl-base",
    "name": "base",
    "envd_access_token": "tok-1",
    "sandbox_domain": "test.dev",
    "state": "running",
    "metadata": {},
}


@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    monkeypatch.setenv("DECLAW_API_KEY", "test-key")
    monkeypatch.setenv("DECLAW_DOMAIN", "api.test.dev")


def _create_sandbox():
    return Sandbox.create(api_key="test-key", domain="api.test.dev")


class TestPtyCreate:
    @respx.mock
    def test_create_default_size(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        route = respx.post(f"{API_URL}/sandboxes/sbx-pty/pty").mock(
            return_value=httpx.Response(200, json={"pid": 99})
        )
        sandbox = _create_sandbox()
        handle = sandbox.pty.create()
        assert isinstance(handle, PtyHandle)
        assert handle.pid == 99
        req = json.loads(route.calls[0].request.content)
        assert req["size"]["cols"] == 80
        assert req["size"]["rows"] == 24

    @respx.mock
    def test_create_custom_size(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        route = respx.post(f"{API_URL}/sandboxes/sbx-pty/pty").mock(
            return_value=httpx.Response(200, json={"pid": 100})
        )
        sandbox = _create_sandbox()
        sandbox.pty.create(size=PtySize(cols=120, rows=40))
        req = json.loads(route.calls[0].request.content)
        assert req["size"]["cols"] == 120
        assert req["size"]["rows"] == 40


class TestPtyKill:
    @respx.mock
    def test_kill_pty(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.delete(f"{API_URL}/sandboxes/sbx-pty/pty/99").mock(
            return_value=httpx.Response(200, json={"killed": True})
        )
        sandbox = _create_sandbox()
        assert sandbox.pty.kill(99) is True


class TestPtySendStdin:
    @respx.mock
    def test_send_stdin(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        route = respx.post(f"{API_URL}/sandboxes/sbx-pty/pty/99/stdin").mock(
            return_value=httpx.Response(200, json={})
        )
        sandbox = _create_sandbox()
        sandbox.pty.send_stdin(99, b"ls -la\n")
        req = json.loads(route.calls[0].request.content)
        assert req["data"] == "ls -la\n"


class TestPtyResize:
    @respx.mock
    def test_resize(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        route = respx.patch(f"{API_URL}/sandboxes/sbx-pty/pty/99").mock(
            return_value=httpx.Response(200, json={})
        )
        sandbox = _create_sandbox()
        sandbox.pty.resize(99, PtySize(cols=200, rows=50))
        req = json.loads(route.calls[0].request.content)
        assert req["size"]["cols"] == 200
        assert req["size"]["rows"] == 50
