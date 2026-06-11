"""Tests for Sandbox.snapshot(), list_snapshots(), and restore() — P6."""

from __future__ import annotations

import httpx
import pytest
import respx

from declaw import AsyncSandbox, Sandbox, Snapshot

API_URL = "https://api.test.dev"

SANDBOX_RESP = {
    "sandbox_id": "sbx-snap",
    "template_id": "tpl-base",
    "name": "base",
    "envd_access_token": "tok-snap",
    "sandbox_domain": "test.dev",
    "state": "running",
    "metadata": {},
}

SNAPSHOT_RESP = {
    "snapshot_id": "snap-manual-001",
    "sandbox_id": "sbx-snap",
    "source": "manual",
    "mem_blob_key": "sandbox/sbx-snap/manual/snap-manual-001/mem",
    "vmstate_blob_key": "sandbox/sbx-snap/manual/snap-manual-001/vmstate",
    "mem_size_bytes": 134217728,
    "pause_duration_ms": 42,
    "created_at": "2026-04-07T10:00:00Z",
}

LIST_RESP = {
    "snapshots": [
        {
            "snapshot_id": "snap-pause-001",
            "sandbox_id": "sbx-snap",
            "source": "pause",
            "mem_blob_key": "sandbox/sbx-snap/pause/mem",
            "vmstate_blob_key": "sandbox/sbx-snap/pause/vmstate",
            "mem_size_bytes": 67108864,
            "pause_duration_ms": 30,
            "created_at": "2026-04-07T09:55:00Z",
        },
        {
            "snapshot_id": "snap-manual-001",
            "sandbox_id": "sbx-snap",
            "source": "manual",
            "mem_blob_key": "sandbox/sbx-snap/manual/snap-manual-001/mem",
            "vmstate_blob_key": "sandbox/sbx-snap/manual/snap-manual-001/vmstate",
            "mem_size_bytes": 134217728,
            "pause_duration_ms": 42,
            "created_at": "2026-04-07T10:00:00Z",
        },
    ]
}

RESTORE_RESP = {
    "sandbox_id": "sbx-snap",
    "node_id": "node-2",
    "snapshot_id": "snap-manual-001",
}


@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    monkeypatch.setenv("DECLAW_API_KEY", "test-key")
    monkeypatch.setenv("DECLAW_DOMAIN", "api.test.dev")


class TestSnapshotSync:
    @respx.mock
    def test_snapshot_returns_snapshot_object(self):
        """POST /sandboxes/:id/snapshot is called; response is parsed into Snapshot."""
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        route = respx.post(f"{API_URL}/sandboxes/sbx-snap/snapshot").mock(
            return_value=httpx.Response(200, json=SNAPSHOT_RESP)
        )

        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        snap = sandbox.snapshot()

        assert route.called
        assert isinstance(snap, Snapshot)
        assert snap.snapshot_id == "snap-manual-001"
        assert snap.sandbox_id == "sbx-snap"
        assert snap.source == "manual"
        assert snap.mem_size_bytes == 134217728
        assert snap.pause_duration_ms == 42

    @respx.mock
    def test_list_snapshots_returns_list(self):
        """GET /sandboxes/:id/snapshots is called; response wrapper is unpacked."""
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.get(f"{API_URL}/sandboxes/sbx-snap/snapshots").mock(
            return_value=httpx.Response(200, json=LIST_RESP)
        )

        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        snaps = sandbox.list_snapshots()

        assert isinstance(snaps, list)
        assert len(snaps) == 2
        assert all(isinstance(s, Snapshot) for s in snaps)
        assert snaps[0].snapshot_id == "snap-pause-001"
        assert snaps[0].source == "pause"
        assert snaps[1].snapshot_id == "snap-manual-001"
        assert snaps[1].source == "manual"

    @respx.mock
    def test_list_snapshots_empty(self):
        """GET /sandboxes/:id/snapshots with empty list returns empty list."""
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.get(f"{API_URL}/sandboxes/sbx-snap/snapshots").mock(
            return_value=httpx.Response(200, json={"snapshots": []})
        )

        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        snaps = sandbox.list_snapshots()

        assert snaps == []

    @respx.mock
    def test_restore_no_snapshot_id_omits_query_param(self):
        """POST /sandboxes/:id/restore with no snapshot_id has no query param."""
        restore_route = respx.post(f"{API_URL}/sandboxes/sbx-snap/restore").mock(
            return_value=httpx.Response(200, json=RESTORE_RESP)
        )
        respx.get(f"{API_URL}/sandboxes/sbx-snap").mock(
            return_value=httpx.Response(200, json=SANDBOX_RESP)
        )

        sandbox = Sandbox.restore("sbx-snap", api_key="test-key", domain="api.test.dev")

        assert restore_route.called
        request = restore_route.calls[0].request
        assert "snapshot_id" not in request.url.query.decode("utf-8")
        assert sandbox.sandbox_id == "sbx-snap"

    @respx.mock
    def test_restore_with_explicit_snapshot_id_passes_query_param(self):
        """POST /sandboxes/:id/restore?snapshot_id=... is sent with the correct param."""
        restore_route = respx.post(f"{API_URL}/sandboxes/sbx-snap/restore").mock(
            return_value=httpx.Response(200, json=RESTORE_RESP)
        )
        respx.get(f"{API_URL}/sandboxes/sbx-snap").mock(
            return_value=httpx.Response(200, json=SANDBOX_RESP)
        )

        sandbox = Sandbox.restore(
            "sbx-snap",
            snapshot_id="snap-manual-001",
            api_key="test-key",
            domain="api.test.dev",
        )

        assert restore_route.called
        request = restore_route.calls[0].request
        assert "snapshot_id=snap-manual-001" in request.url.query.decode("utf-8")
        assert sandbox.sandbox_id == "sbx-snap"


class TestSnapshotAsync:
    @respx.mock
    @pytest.mark.asyncio
    async def test_async_snapshot_returns_snapshot_object(self):
        """Async POST /sandboxes/:id/snapshot returns a Snapshot."""
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        route = respx.post(f"{API_URL}/sandboxes/sbx-snap/snapshot").mock(
            return_value=httpx.Response(200, json=SNAPSHOT_RESP)
        )

        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        snap = await sandbox.snapshot()

        assert route.called
        assert isinstance(snap, Snapshot)
        assert snap.snapshot_id == "snap-manual-001"
        assert snap.source == "manual"

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_list_snapshots_returns_list(self):
        """Async GET /sandboxes/:id/snapshots unpacks the wrapper and returns a list."""
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.get(f"{API_URL}/sandboxes/sbx-snap/snapshots").mock(
            return_value=httpx.Response(200, json=LIST_RESP)
        )

        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        snaps = await sandbox.list_snapshots()

        assert len(snaps) == 2
        assert all(isinstance(s, Snapshot) for s in snaps)

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_restore_no_snapshot_id_omits_query_param(self):
        """Async restore without snapshot_id sends no query param."""
        restore_route = respx.post(f"{API_URL}/sandboxes/sbx-snap/restore").mock(
            return_value=httpx.Response(200, json=RESTORE_RESP)
        )
        respx.get(f"{API_URL}/sandboxes/sbx-snap").mock(
            return_value=httpx.Response(200, json=SANDBOX_RESP)
        )

        sandbox = await AsyncSandbox.restore("sbx-snap", api_key="test-key", domain="api.test.dev")

        assert restore_route.called
        request = restore_route.calls[0].request
        assert "snapshot_id" not in request.url.query.decode("utf-8")
        assert sandbox.sandbox_id == "sbx-snap"

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_restore_with_explicit_snapshot_id_passes_query_param(self):
        """Async restore with snapshot_id sends the correct query param."""
        restore_route = respx.post(f"{API_URL}/sandboxes/sbx-snap/restore").mock(
            return_value=httpx.Response(200, json=RESTORE_RESP)
        )
        respx.get(f"{API_URL}/sandboxes/sbx-snap").mock(
            return_value=httpx.Response(200, json=SANDBOX_RESP)
        )

        sandbox = await AsyncSandbox.restore(
            "sbx-snap",
            snapshot_id="snap-manual-001",
            api_key="test-key",
            domain="api.test.dev",
        )

        assert restore_route.called
        request = restore_route.calls[0].request
        assert "snapshot_id=snap-manual-001" in request.url.query.decode("utf-8")
        assert sandbox.sandbox_id == "sbx-snap"


class TestSnapshotModel:
    def test_from_dict_full(self):
        snap = Snapshot.from_dict(SNAPSHOT_RESP)
        assert snap.snapshot_id == "snap-manual-001"
        assert snap.sandbox_id == "sbx-snap"
        assert snap.source == "manual"
        assert snap.mem_blob_key == "sandbox/sbx-snap/manual/snap-manual-001/mem"
        assert snap.vmstate_blob_key == "sandbox/sbx-snap/manual/snap-manual-001/vmstate"
        assert snap.mem_size_bytes == 134217728
        assert snap.pause_duration_ms == 42
        assert snap.created_at == "2026-04-07T10:00:00Z"

    def test_from_dict_optional_fields_absent(self):
        snap = Snapshot.from_dict(
            {
                "snapshot_id": "snap-x",
                "sandbox_id": "sbx-y",
                "source": "periodic",
                "created_at": "2026-04-07T10:00:00Z",
            }
        )
        assert snap.mem_blob_key == ""
        assert snap.vmstate_blob_key == ""
        assert snap.mem_size_bytes is None
        assert snap.pause_duration_ms is None
