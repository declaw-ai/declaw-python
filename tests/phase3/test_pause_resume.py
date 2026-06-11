import httpx
import pytest
import respx

from declaw import AsyncSandbox, Sandbox, SandboxLifecycle, SnapshotInfo

API_URL = "https://api.test.dev"
SANDBOX_RESP = {
    "sandbox_id": "sbx-pause",
    "template_id": "tpl-base",
    "name": "base",
    "envd_access_token": "tok-1",
    "sandbox_domain": "test.dev",
    "state": "running",
    "metadata": {},
}
PAUSED_RESP = {**SANDBOX_RESP, "state": "paused"}


@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    monkeypatch.setenv("DECLAW_API_KEY", "test-key")
    monkeypatch.setenv("DECLAW_DOMAIN", "api.test.dev")


class TestSyncPauseResume:
    @respx.mock
    def test_pause(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-pause/pause").mock(
            return_value=httpx.Response(200, json={})
        )
        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        sandbox.pause()

    @respx.mock
    def test_pause_then_connect_resumes(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-pause/pause").mock(
            return_value=httpx.Response(200, json={})
        )
        respx.get(f"{API_URL}/sandboxes/sbx-pause").mock(
            return_value=httpx.Response(200, json=SANDBOX_RESP)
        )
        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        sandbox.pause()
        resumed = Sandbox.connect("sbx-pause", api_key="test-key", domain="api.test.dev")
        assert resumed.sandbox_id == "sbx-pause"

    @respx.mock
    def test_create_snapshot(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-pause/snapshot").mock(
            return_value=httpx.Response(
                200,
                json={
                    "snapshot_id": "snap-1",
                    "sandbox_id": "sbx-pause",
                    "created_at": "2026-01-01T12:00:00",
                },
            )
        )
        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        snap = sandbox.create_snapshot()
        assert isinstance(snap, SnapshotInfo)
        assert snap.snapshot_id == "snap-1"


class TestAsyncPauseResume:
    @respx.mock
    @pytest.mark.asyncio
    async def test_async_pause(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-pause/pause").mock(
            return_value=httpx.Response(200, json={})
        )
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        await sandbox.pause()

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_create_snapshot(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-pause/snapshot").mock(
            return_value=httpx.Response(
                200,
                json={
                    "snapshot_id": "snap-2",
                    "sandbox_id": "sbx-pause",
                },
            )
        )
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        snap = await sandbox.create_snapshot()
        assert snap.snapshot_id == "snap-2"


class TestSandboxLifecycleConfig:
    def test_defaults(self):
        lc = SandboxLifecycle()
        assert lc.on_timeout == "kill"
        assert lc.auto_resume is False

    def test_pause_auto_resume(self):
        lc = SandboxLifecycle(on_timeout="pause", auto_resume=True)
        d = lc.to_dict()
        assert d == {"on_timeout": "pause", "auto_resume": True}
        restored = SandboxLifecycle.from_dict(d)
        assert restored.on_timeout == "pause"
        assert restored.auto_resume is True

    @respx.mock
    def test_create_with_lifecycle(self):
        route = respx.post(f"{API_URL}/sandboxes").mock(
            return_value=httpx.Response(201, json=SANDBOX_RESP)
        )
        Sandbox.create(
            lifecycle=SandboxLifecycle(on_timeout="pause", auto_resume=True),
            api_key="test-key",
            domain="api.test.dev",
        )
        import json

        body = json.loads(route.calls[0].request.content)
        assert body["lifecycle"]["on_timeout"] == "pause"
        assert body["lifecycle"]["auto_resume"] is True
