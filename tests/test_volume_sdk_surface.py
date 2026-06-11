"""Tests for the full volume SDK surface (sync + async).

Covers: attach mode/subpath, snapshot, empty, ingest, download, the model's
new backend/quota_bytes/updated_at fields, the files sub-API (write/read/
list/info/exists/remove/rename/mkdir + CAS if_version), and the locks
sub-API (acquire/release/renew/status). The HTTP layer is mocked with respx
and we assert the exact method/path/query/body/headers and response parsing.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from declaw import (
    AsyncVolumes,
    ConflictException,
    FileEntry,
    Volume,
    VolumeAttachment,
    Volumes,
)

API_URL = "https://api.test.dev"

VOLUME_RESP = {
    "volume_id": "vol-1",
    "owner_id": "owner-1",
    "name": "data",
    "blob_key": "volumes/owner-1/vol-1",
    "size_bytes": 4096,
    "content_type": "application/gzip",
    "metadata": {"k": "v"},
    "created_at": "2026-01-01T00:00:00Z",
    "backend": "file-granular",
    "quota_bytes": 1073741824,
    "updated_at": "2026-01-02T00:00:00Z",
}

FILE_ENTRY = {
    "name": "a.txt",
    "path": "/a.txt",
    "is_dir": False,
    "size": 12,
    "mod_time": "2026-01-01T00:00:00Z",
    "mode": 420,
}


@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    monkeypatch.setenv("DECLAW_API_KEY", "test-key")
    monkeypatch.setenv("DECLAW_DOMAIN", "api.test.dev")


# ---------------------------------------------------------------------------
# Model parity: backend / quota_bytes / updated_at
# ---------------------------------------------------------------------------
class TestVolumeModelParity:
    def test_from_dict_parses_new_fields(self):
        vol = Volume.from_dict(VOLUME_RESP)
        assert vol.backend == "file-granular"
        assert vol.quota_bytes == 1073741824
        assert vol.updated_at == "2026-01-02T00:00:00Z"

    def test_from_dict_defaults_missing_new_fields(self):
        vol = Volume.from_dict({"volume_id": "v"})
        assert vol.backend == ""
        assert vol.quota_bytes == 0
        assert vol.updated_at == ""


# ---------------------------------------------------------------------------
# A. attach mode / subpath
# ---------------------------------------------------------------------------
class TestAttachModeSubpath:
    def test_default_omits_mode_and_subpath(self):
        assert VolumeAttachment("v", "/m").to_dict() == {
            "volume_id": "v",
            "mount_path": "/m",
        }

    def test_copy_mode_is_omitted(self):
        assert VolumeAttachment("v", "/m", mode="copy").to_dict() == {
            "volume_id": "v",
            "mount_path": "/m",
        }

    def test_mount_mode_and_subpath_serialized(self):
        assert VolumeAttachment("v", "/m", mode="mount", subpath="sub/dir").to_dict() == {
            "volume_id": "v",
            "mount_path": "/m",
            "mode": "mount",
            "subpath": "sub/dir",
        }

    def test_mount_ro(self):
        assert VolumeAttachment("v", "/m", mode="mount-ro").to_dict()["mode"] == "mount-ro"

    def test_volume_attach_helper_passes_mode_subpath(self):
        vol = Volume.from_dict(VOLUME_RESP)
        att = vol.attach("/data", mode="mount-ro", subpath="x")
        assert att.to_dict() == {
            "volume_id": "vol-1",
            "mount_path": "/data",
            "mode": "mount-ro",
            "subpath": "x",
        }


# ---------------------------------------------------------------------------
# B. snapshot
# ---------------------------------------------------------------------------
class TestSnapshot:
    @respx.mock
    def test_snapshot_with_name(self):
        route = respx.post(f"{API_URL}/sandboxes/sbx-1/volumes/snapshot").mock(
            return_value=httpx.Response(201, json=VOLUME_RESP)
        )
        vol = Volumes.snapshot("sbx-1", "/work/out", "my-snap")
        assert route.called
        params = route.calls.last.request.url.params
        assert params.get("path") == "/work/out"
        assert params.get("name") == "my-snap"
        assert isinstance(vol, Volume)
        assert vol.volume_id == "vol-1"

    @respx.mock
    def test_snapshot_without_name_omits_param(self):
        route = respx.post(f"{API_URL}/sandboxes/sbx-1/volumes/snapshot").mock(
            return_value=httpx.Response(201, json=VOLUME_RESP)
        )
        Volumes.snapshot("sbx-1", "/work/out")
        params = route.calls.last.request.url.params
        assert params.get("path") == "/work/out"
        assert "name" not in params

    @respx.mock
    def test_snapshot_bad_path_raises(self):
        respx.post(f"{API_URL}/sandboxes/sbx-1/volumes/snapshot").mock(
            return_value=httpx.Response(400, json={"message": "synthetic path"})
        )
        with pytest.raises(Exception):
            Volumes.snapshot("sbx-1", "/proc")

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_snapshot(self):
        route = respx.post(f"{API_URL}/sandboxes/sbx-1/volumes/snapshot").mock(
            return_value=httpx.Response(201, json=VOLUME_RESP)
        )
        vol = await AsyncVolumes.snapshot("sbx-1", "/work/out", "my-snap")
        params = route.calls.last.request.url.params
        assert params.get("path") == "/work/out"
        assert params.get("name") == "my-snap"
        assert vol.volume_id == "vol-1"


# ---------------------------------------------------------------------------
# C. empty
# ---------------------------------------------------------------------------
class TestEmpty:
    @respx.mock
    def test_empty(self):
        route = respx.post(f"{API_URL}/volumes/empty").mock(
            return_value=httpx.Response(201, json=VOLUME_RESP)
        )
        vol = Volumes.empty("scratch")
        assert route.called
        assert route.calls.last.request.url.params.get("name") == "scratch"
        assert not route.calls.last.request.content  # no body
        assert vol.backend == "file-granular"

    @respx.mock
    def test_empty_backend_unconfigured_raises(self):
        respx.post(f"{API_URL}/volumes/empty").mock(
            return_value=httpx.Response(503, json={"message": "no backend"})
        )
        with pytest.raises(Exception):
            Volumes.empty("scratch")

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_empty(self):
        route = respx.post(f"{API_URL}/volumes/empty").mock(
            return_value=httpx.Response(201, json=VOLUME_RESP)
        )
        vol = await AsyncVolumes.empty("scratch")
        assert route.calls.last.request.url.params.get("name") == "scratch"
        assert vol.volume_id == "vol-1"


# ---------------------------------------------------------------------------
# D. ingest
# ---------------------------------------------------------------------------
class TestIngest:
    @respx.mock
    def test_ingest_sends_gzip_content_type_and_body(self):
        route = respx.post(f"{API_URL}/volumes/ingest").mock(
            return_value=httpx.Response(201, json=VOLUME_RESP)
        )
        vol = Volumes.ingest("seeded", b"\x1f\x8b rawtargz")
        req = route.calls.last.request
        assert req.url.params.get("name") == "seeded"
        assert req.headers["content-type"] == "application/gzip"
        assert req.content == b"\x1f\x8b rawtargz"
        assert vol.volume_id == "vol-1"

    @respx.mock
    def test_ingest_quota_exceeded_raises(self):
        respx.post(f"{API_URL}/volumes/ingest").mock(
            return_value=httpx.Response(413, json={"message": "quota"})
        )
        with pytest.raises(Exception):
            Volumes.ingest("seeded", b"data")

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_ingest(self):
        route = respx.post(f"{API_URL}/volumes/ingest").mock(
            return_value=httpx.Response(201, json=VOLUME_RESP)
        )
        await AsyncVolumes.ingest("seeded", b"data")
        assert route.calls.last.request.headers["content-type"] == "application/gzip"


# ---------------------------------------------------------------------------
# create: Content-Type application/gzip
# ---------------------------------------------------------------------------
class TestCreateContentType:
    @respx.mock
    def test_create_sends_application_gzip(self):
        route = respx.post(f"{API_URL}/volumes").mock(
            return_value=httpx.Response(201, json=VOLUME_RESP)
        )
        Volumes.create("data", b"\x1f\x8b body")
        assert route.calls.last.request.headers["content-type"] == "application/gzip"


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------
class TestDownload:
    @respx.mock
    def test_download_returns_bytes(self):
        route = respx.get(f"{API_URL}/volumes/vol-1/download").mock(
            return_value=httpx.Response(200, content=b"\x1f\x8b blob")
        )
        data = Volumes.download("vol-1")
        assert route.called
        assert data == b"\x1f\x8b blob"

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_download(self):
        respx.get(f"{API_URL}/volumes/vol-1/download").mock(
            return_value=httpx.Response(200, content=b"\x1f\x8b blob")
        )
        data = await AsyncVolumes.download("vol-1")
        assert data == b"\x1f\x8b blob"


# ---------------------------------------------------------------------------
# E. files API (sync)
# ---------------------------------------------------------------------------
class TestFilesSync:
    @respx.mock
    def test_write_unconditional(self):
        route = respx.put(f"{API_URL}/volumes/vol-1/files/raw").mock(
            return_value=httpx.Response(200, json={"path": "/a.txt"})
        )
        out = Volumes.files("vol-1").write("/a.txt", b"hello")
        req = route.calls.last.request
        assert req.url.params.get("path") == "/a.txt"
        assert "if_version" not in req.url.params
        assert req.headers["content-type"] == "application/octet-stream"
        assert req.content == b"hello"
        assert out == "/a.txt"

    @respx.mock
    def test_write_with_if_version(self):
        route = respx.put(f"{API_URL}/volumes/vol-1/files/raw").mock(
            return_value=httpx.Response(200, json={"path": "/a.txt"})
        )
        Volumes.files("vol-1").write("/a.txt", b"hello", if_version="v7")
        assert route.calls.last.request.url.params.get("if_version") == "v7"

    @respx.mock
    def test_write_version_mismatch_raises_conflict(self):
        respx.put(f"{API_URL}/volumes/vol-1/files/raw").mock(
            return_value=httpx.Response(409, json={"message": "version mismatch"})
        )
        with pytest.raises(ConflictException):
            Volumes.files("vol-1").write("/a.txt", b"x", if_version="stale")

    @respx.mock
    def test_read(self):
        route = respx.get(f"{API_URL}/volumes/vol-1/files/raw").mock(
            return_value=httpx.Response(200, content=b"hello")
        )
        out = Volumes.files("vol-1").read("/a.txt")
        assert route.calls.last.request.url.params.get("path") == "/a.txt"
        assert out == b"hello"

    @respx.mock
    def test_list(self):
        route = respx.get(f"{API_URL}/volumes/vol-1/files/list").mock(
            return_value=httpx.Response(200, json={"entries": [FILE_ENTRY]})
        )
        entries = Volumes.files("vol-1").list("/dir")
        assert route.calls.last.request.url.params.get("path") == "/dir"
        assert len(entries) == 1
        assert isinstance(entries[0], FileEntry)
        assert entries[0].name == "a.txt"
        assert entries[0].mode == 420

    @respx.mock
    def test_info_carries_version(self):
        route = respx.get(f"{API_URL}/volumes/vol-1/files/info").mock(
            return_value=httpx.Response(200, json=dict(FILE_ENTRY, version="v42"))
        )
        entry = Volumes.files("vol-1").info("/a.txt")
        assert route.calls.last.request.url.params.get("path") == "/a.txt"
        assert entry.version == "v42"

    @respx.mock
    def test_exists(self):
        route = respx.get(f"{API_URL}/volumes/vol-1/files/exists").mock(
            return_value=httpx.Response(200, json={"exists": True})
        )
        assert Volumes.files("vol-1").exists("/a.txt") is True
        assert route.calls.last.request.url.params.get("path") == "/a.txt"

    @respx.mock
    def test_remove_default_non_recursive(self):
        route = respx.delete(f"{API_URL}/volumes/vol-1/files").mock(
            return_value=httpx.Response(204)
        )
        Volumes.files("vol-1").remove("/a.txt")
        params = route.calls.last.request.url.params
        assert params.get("path") == "/a.txt"
        assert params.get("recursive") == "false"

    @respx.mock
    def test_remove_recursive(self):
        route = respx.delete(f"{API_URL}/volumes/vol-1/files").mock(
            return_value=httpx.Response(204)
        )
        Volumes.files("vol-1").remove("/dir", recursive=True)
        assert route.calls.last.request.url.params.get("recursive") == "true"

    @respx.mock
    def test_rename(self):
        route = respx.patch(f"{API_URL}/volumes/vol-1/files").mock(
            return_value=httpx.Response(200, json={"old_path": "/a", "new_path": "/b"})
        )
        out = Volumes.files("vol-1").rename("/a", "/b")
        body = json.loads(route.calls.last.request.content)
        assert body == {"old_path": "/a", "new_path": "/b"}
        assert out == {"old_path": "/a", "new_path": "/b"}

    @respx.mock
    def test_mkdir(self):
        route = respx.post(f"{API_URL}/volumes/vol-1/files/mkdir").mock(
            return_value=httpx.Response(201, json={"path": "/newdir"})
        )
        out = Volumes.files("vol-1").mkdir("/newdir")
        body = json.loads(route.calls.last.request.content)
        assert body == {"path": "/newdir"}
        assert out == "/newdir"

    @respx.mock
    def test_write_on_tarball_backend_conflict(self):
        respx.put(f"{API_URL}/volumes/vol-1/files/raw").mock(
            return_value=httpx.Response(409, json={"message": "tarball backend"})
        )
        with pytest.raises(ConflictException):
            Volumes.files("vol-1").write("/a.txt", b"x")


# ---------------------------------------------------------------------------
# E. files API (async)
# ---------------------------------------------------------------------------
class TestFilesAsync:
    @respx.mock
    @pytest.mark.asyncio
    async def test_async_write_with_if_version(self):
        route = respx.put(f"{API_URL}/volumes/vol-1/files/raw").mock(
            return_value=httpx.Response(200, json={"path": "/a.txt"})
        )
        out = await AsyncVolumes.files("vol-1").write("/a.txt", b"hi", if_version="v1")
        req = route.calls.last.request
        assert req.url.params.get("if_version") == "v1"
        assert req.headers["content-type"] == "application/octet-stream"
        assert out == "/a.txt"

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_read(self):
        respx.get(f"{API_URL}/volumes/vol-1/files/raw").mock(
            return_value=httpx.Response(200, content=b"hello")
        )
        assert await AsyncVolumes.files("vol-1").read("/a.txt") == b"hello"

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_list(self):
        respx.get(f"{API_URL}/volumes/vol-1/files/list").mock(
            return_value=httpx.Response(200, json={"entries": [FILE_ENTRY]})
        )
        entries = await AsyncVolumes.files("vol-1").list()
        assert entries[0].name == "a.txt"

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_info(self):
        respx.get(f"{API_URL}/volumes/vol-1/files/info").mock(
            return_value=httpx.Response(200, json=dict(FILE_ENTRY, version="v9"))
        )
        entry = await AsyncVolumes.files("vol-1").info("/a.txt")
        assert entry.version == "v9"

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_exists(self):
        respx.get(f"{API_URL}/volumes/vol-1/files/exists").mock(
            return_value=httpx.Response(200, json={"exists": False})
        )
        assert await AsyncVolumes.files("vol-1").exists("/x") is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_remove(self):
        route = respx.delete(f"{API_URL}/volumes/vol-1/files").mock(
            return_value=httpx.Response(204)
        )
        await AsyncVolumes.files("vol-1").remove("/dir", recursive=True)
        assert route.calls.last.request.url.params.get("recursive") == "true"

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_rename(self):
        route = respx.patch(f"{API_URL}/volumes/vol-1/files").mock(
            return_value=httpx.Response(200, json={"old_path": "/a", "new_path": "/b"})
        )
        await AsyncVolumes.files("vol-1").rename("/a", "/b")
        assert json.loads(route.calls.last.request.content) == {
            "old_path": "/a",
            "new_path": "/b",
        }

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_mkdir(self):
        route = respx.post(f"{API_URL}/volumes/vol-1/files/mkdir").mock(
            return_value=httpx.Response(201, json={"path": "/d"})
        )
        out = await AsyncVolumes.files("vol-1").mkdir("/d")
        assert json.loads(route.calls.last.request.content) == {"path": "/d"}
        assert out == "/d"


# ---------------------------------------------------------------------------
# G. locks API (sync)
# ---------------------------------------------------------------------------
LOCK_RESP = {"token": "tok-1", "ttl_seconds": 30, "expires_at": "2026-01-01T00:00:30Z"}


class TestLocksSync:
    @respx.mock
    def test_acquire_with_ttl(self):
        route = respx.post(f"{API_URL}/volumes/vol-1/locks").mock(
            return_value=httpx.Response(200, json=LOCK_RESP)
        )
        out = Volumes.locks("vol-1").acquire("/a.txt", ttl_seconds=30)
        body = json.loads(route.calls.last.request.content)
        assert body == {"path": "/a.txt", "ttl_seconds": 30}
        assert out["token"] == "tok-1"

    @respx.mock
    def test_acquire_without_ttl_omits_field(self):
        route = respx.post(f"{API_URL}/volumes/vol-1/locks").mock(
            return_value=httpx.Response(200, json=LOCK_RESP)
        )
        Volumes.locks("vol-1").acquire("/a.txt")
        assert json.loads(route.calls.last.request.content) == {"path": "/a.txt"}

    @respx.mock
    def test_acquire_already_held_conflict(self):
        respx.post(f"{API_URL}/volumes/vol-1/locks").mock(
            return_value=httpx.Response(409, json={"message": "already held"})
        )
        with pytest.raises(ConflictException):
            Volumes.locks("vol-1").acquire("/a.txt")

    @respx.mock
    def test_release_sends_json_body(self):
        route = respx.delete(f"{API_URL}/volumes/vol-1/locks").mock(
            return_value=httpx.Response(200, json={"released": True})
        )
        out = Volumes.locks("vol-1").release("/a.txt", "tok-1")
        body = json.loads(route.calls.last.request.content)
        assert body == {"path": "/a.txt", "token": "tok-1"}
        assert out is True

    @respx.mock
    def test_renew_with_ttl(self):
        route = respx.post(f"{API_URL}/volumes/vol-1/locks/renew").mock(
            return_value=httpx.Response(200, json={"ttl_seconds": 60})
        )
        Volumes.locks("vol-1").renew("/a.txt", "tok-1", ttl_seconds=60)
        body = json.loads(route.calls.last.request.content)
        assert body == {"path": "/a.txt", "token": "tok-1", "ttl_seconds": 60}

    @respx.mock
    def test_status(self):
        route = respx.get(f"{API_URL}/volumes/vol-1/locks").mock(
            return_value=httpx.Response(200, json={"held": True, "expires_in_ms": 1500})
        )
        out = Volumes.locks("vol-1").status("/a.txt")
        assert route.calls.last.request.url.params.get("path") == "/a.txt"
        assert out == {"held": True, "expires_in_ms": 1500}


# ---------------------------------------------------------------------------
# G. locks API (async)
# ---------------------------------------------------------------------------
class TestLocksAsync:
    @respx.mock
    @pytest.mark.asyncio
    async def test_async_acquire(self):
        route = respx.post(f"{API_URL}/volumes/vol-1/locks").mock(
            return_value=httpx.Response(200, json=LOCK_RESP)
        )
        out = await AsyncVolumes.locks("vol-1").acquire("/a.txt", ttl_seconds=30)
        assert json.loads(route.calls.last.request.content) == {
            "path": "/a.txt",
            "ttl_seconds": 30,
        }
        assert out["token"] == "tok-1"

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_release(self):
        route = respx.delete(f"{API_URL}/volumes/vol-1/locks").mock(
            return_value=httpx.Response(200, json={"released": True})
        )
        out = await AsyncVolumes.locks("vol-1").release("/a.txt", "tok-1")
        assert json.loads(route.calls.last.request.content) == {
            "path": "/a.txt",
            "token": "tok-1",
        }
        assert out is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_renew(self):
        route = respx.post(f"{API_URL}/volumes/vol-1/locks/renew").mock(
            return_value=httpx.Response(200, json={"ttl_seconds": 60})
        )
        await AsyncVolumes.locks("vol-1").renew("/a.txt", "tok-1")
        assert json.loads(route.calls.last.request.content) == {
            "path": "/a.txt",
            "token": "tok-1",
        }

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_status(self):
        route = respx.get(f"{API_URL}/volumes/vol-1/locks").mock(
            return_value=httpx.Response(200, json={"held": False, "expires_in_ms": 0})
        )
        out = await AsyncVolumes.locks("vol-1").status("/a.txt")
        assert route.calls.last.request.url.params.get("path") == "/a.txt"
        assert out == {"held": False, "expires_in_ms": 0}
