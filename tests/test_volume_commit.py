"""Tests for Volumes.commit() and AsyncVolumes.commit()."""

from __future__ import annotations

import httpx
import pytest
import respx

from declaw import AsyncVolumes, Volume, Volumes

API_URL = "https://api.test.dev"

COMMIT_RESP = {
    "volume_id": "vol-new",
    "owner_id": "owner-1",
    "name": "snapshot",
    "blob_key": "volumes/owner-1/vol-new",
    "size_bytes": 2048,
    "content_type": "application/gzip",
    "created_at": "2026-01-01T00:00:00Z",
}


@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    monkeypatch.setenv("DECLAW_API_KEY", "test-key")
    monkeypatch.setenv("DECLAW_DOMAIN", "api.test.dev")


class TestVolumeCommitSync:
    @respx.mock
    def test_commit_with_name(self):
        """POST /sandboxes/:id/volumes/:vid/commit with name passes the query param."""
        route = respx.post(f"{API_URL}/sandboxes/sbx-1/volumes/vol-src/commit").mock(
            return_value=httpx.Response(201, json=COMMIT_RESP)
        )

        vol = Volumes.commit("sbx-1", "vol-src", "snapshot")

        assert route.called
        assert route.calls.last.request.url.params.get("name") == "snapshot"
        assert isinstance(vol, Volume)
        assert vol.volume_id == "vol-new"
        assert vol.name == "snapshot"
        assert vol.size_bytes == 2048

    @respx.mock
    def test_commit_without_name_omits_query_param(self):
        """Commit with no name sends no `name` query param; server defaults it."""
        resp = dict(COMMIT_RESP, name="src-commit")
        route = respx.post(f"{API_URL}/sandboxes/sbx-1/volumes/vol-src/commit").mock(
            return_value=httpx.Response(201, json=resp)
        )

        vol = Volumes.commit("sbx-1", "vol-src")

        assert route.called
        assert "name" not in route.calls.last.request.url.params
        assert vol.name == "src-commit"

    @respx.mock
    def test_commit_not_attached_raises(self):
        """A 400 (not attached) surfaces as an exception."""
        respx.post(f"{API_URL}/sandboxes/sbx-1/volumes/vol-src/commit").mock(
            return_value=httpx.Response(
                400, json={"message": "volume is not attached to this sandbox"}
            )
        )

        with pytest.raises(Exception):
            Volumes.commit("sbx-1", "vol-src")

    @respx.mock
    def test_commit_sandbox_paused_raises(self):
        """A 409 (paused) surfaces as an exception."""
        respx.post(f"{API_URL}/sandboxes/sbx-1/volumes/vol-src/commit").mock(
            return_value=httpx.Response(409, json={"message": "sandbox is paused"})
        )

        with pytest.raises(Exception):
            Volumes.commit("sbx-1", "vol-src")


class TestVolumeCommitAsync:
    @respx.mock
    @pytest.mark.asyncio
    async def test_async_commit_with_name(self):
        route = respx.post(f"{API_URL}/sandboxes/sbx-1/volumes/vol-src/commit").mock(
            return_value=httpx.Response(201, json=COMMIT_RESP)
        )

        vol = await AsyncVolumes.commit("sbx-1", "vol-src", "snapshot")

        assert route.called
        assert route.calls.last.request.url.params.get("name") == "snapshot"
        assert isinstance(vol, Volume)
        assert vol.volume_id == "vol-new"

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_commit_without_name_omits_query_param(self):
        resp = dict(COMMIT_RESP, name="src-commit")
        route = respx.post(f"{API_URL}/sandboxes/sbx-1/volumes/vol-src/commit").mock(
            return_value=httpx.Response(201, json=resp)
        )

        vol = await AsyncVolumes.commit("sbx-1", "vol-src")

        assert route.called
        assert "name" not in route.calls.last.request.url.params
        assert vol.name == "src-commit"
