"""Async mirror of declaw.volumes — same contract, awaitable."""

from __future__ import annotations

import os
from pathlib import Path
from typing import (  # noqa: UP035
    Any,
    AsyncIterable,
    BinaryIO,
    Dict,
    Iterable,
    List,
    Optional,
    Union,
)

from declaw.api.async_client import AsyncApiClient, get_shared_async_client
from declaw.connection_config import ConnectionConfig
from declaw.volumes.main import FileEntry, Volume, _pack_path_to_tar_gz


async def _shared_client(
    api_key: Optional[str],
    domain: Optional[str],
    request_timeout: Optional[float],
) -> AsyncApiClient:
    """Return a process-wide AsyncApiClient keyed by the caller's config
    and current event loop. Shared — do not aclose it."""
    config = ConnectionConfig(
        api_key=api_key or ConnectionConfig().api_key,
        domain=domain or ConnectionConfig.default_domain(),
        request_timeout=request_timeout,
    )
    return await get_shared_async_client(config)


class AsyncVolumeFiles:
    """Async files sub-API for a single file-granular volume.

    Obtain via ``AsyncVolumes.files(volume_id)``."""

    def __init__(
        self,
        volume_id: str,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ):
        self.volume_id = volume_id
        self._api_key = api_key
        self._domain = domain
        self._request_timeout = request_timeout

    async def _client(self) -> AsyncApiClient:
        return await _shared_client(self._api_key, self._domain, self._request_timeout)

    async def write(
        self,
        path: str,
        data: Union[bytes, BinaryIO, Iterable[bytes], AsyncIterable[bytes]],
        *,
        if_version: Optional[str] = None,
    ) -> str:
        """Write raw bytes to ``path``. Pass ``if_version`` for a CAS write
        (409 -> ``ConflictException`` on mismatch). Returns the written path."""
        params: Dict[str, Any] = {"path": path}
        if if_version is not None:
            params["if_version"] = if_version
        client = await self._client()
        resp = await client.put(
            f"/volumes/{self.volume_id}/files/raw",
            params=params,
            content=data,
            headers={"Content-Type": "application/octet-stream"},
            timeout=self._request_timeout,
        )
        return (resp.json() or {}).get("path", path)

    async def read(self, path: str) -> bytes:
        """Read ``path`` and return its raw bytes."""
        client = await self._client()
        resp = await client.get(
            f"/volumes/{self.volume_id}/files/raw",
            params={"path": path},
            timeout=self._request_timeout,
        )
        return resp.content

    async def list(self, path: str = "/") -> List[FileEntry]:
        """List entries under directory ``path``."""
        client = await self._client()
        resp = await client.get(
            f"/volumes/{self.volume_id}/files/list",
            params={"path": path},
            timeout=self._request_timeout,
        )
        payload = resp.json() or {}
        return [FileEntry.from_dict(e) for e in payload.get("entries", [])]

    async def info(self, path: str) -> FileEntry:
        """Stat ``path``. ``FileEntry.version`` is the CAS token for ``write``."""
        client = await self._client()
        resp = await client.get(
            f"/volumes/{self.volume_id}/files/info",
            params={"path": path},
            timeout=self._request_timeout,
        )
        return FileEntry.from_dict(resp.json() or {})

    async def exists(self, path: str) -> bool:
        """Return whether ``path`` exists."""
        client = await self._client()
        resp = await client.get(
            f"/volumes/{self.volume_id}/files/exists",
            params={"path": path},
            timeout=self._request_timeout,
        )
        return bool((resp.json() or {}).get("exists", False))

    async def remove(self, path: str, *, recursive: bool = False) -> None:
        """Remove ``path``. Pass ``recursive=True`` for a directory tree."""
        client = await self._client()
        await client.delete(
            f"/volumes/{self.volume_id}/files",
            params={"path": path, "recursive": "true" if recursive else "false"},
            timeout=self._request_timeout,
        )

    async def rename(self, old_path: str, new_path: str) -> Dict[str, str]:
        """Rename/move ``old_path`` to ``new_path``."""
        client = await self._client()
        resp = await client.patch(
            f"/volumes/{self.volume_id}/files",
            json={"old_path": old_path, "new_path": new_path},
            timeout=self._request_timeout,
        )
        return resp.json() or {}

    async def mkdir(self, path: str) -> str:
        """Create directory ``path``. Returns the created path."""
        client = await self._client()
        resp = await client.post(
            f"/volumes/{self.volume_id}/files/mkdir",
            json={"path": path},
            timeout=self._request_timeout,
        )
        return (resp.json() or {}).get("path", path)


class AsyncVolumeLocks:
    """Async advisory-lock sub-API for a single volume.

    Obtain via ``AsyncVolumes.locks(volume_id)``."""

    def __init__(
        self,
        volume_id: str,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ):
        self.volume_id = volume_id
        self._api_key = api_key
        self._domain = domain
        self._request_timeout = request_timeout

    async def _client(self) -> AsyncApiClient:
        return await _shared_client(self._api_key, self._domain, self._request_timeout)

    async def acquire(self, path: str, *, ttl_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Acquire the lock over ``path``. Returns
        ``{"token", "ttl_seconds", "expires_at"}``. 409 if already held."""
        body: Dict[str, Any] = {"path": path}
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        client = await self._client()
        resp = await client.post(
            f"/volumes/{self.volume_id}/locks",
            json=body,
            timeout=self._request_timeout,
        )
        return resp.json() or {}

    async def release(self, path: str, token: str) -> bool:
        """Release the lock. Returns ``released``. 409 if not the holder."""
        client = await self._client()
        resp = await client.delete(
            f"/volumes/{self.volume_id}/locks",
            json={"path": path, "token": token},
            timeout=self._request_timeout,
        )
        return bool((resp.json() or {}).get("released", False))

    async def renew(
        self, path: str, token: str, *, ttl_seconds: Optional[int] = None
    ) -> Dict[str, Any]:
        """Renew the lock. 409 if not the holder."""
        body: Dict[str, Any] = {"path": path, "token": token}
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        client = await self._client()
        resp = await client.post(
            f"/volumes/{self.volume_id}/locks/renew",
            json=body,
            timeout=self._request_timeout,
        )
        return resp.json() or {}

    async def status(self, path: str) -> Dict[str, Any]:
        """Return ``{"held": bool, "expires_in_ms": int}`` for ``path``."""
        client = await self._client()
        resp = await client.get(
            f"/volumes/{self.volume_id}/locks",
            params={"path": path},
            timeout=self._request_timeout,
        )
        return resp.json() or {}


class AsyncVolumes:
    """Async client for the /volumes CRUD API."""

    @staticmethod
    async def create(
        name: str,
        data: Union[
            bytes, BinaryIO, Iterable[bytes], AsyncIterable[bytes], str, "os.PathLike[str]"
        ],
        *,
        content_type: str = "application/gzip",
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> Volume:
        if isinstance(data, (str, os.PathLike)):
            path = Path(data)
            if not path.exists():
                raise FileNotFoundError(f"volume source path does not exist: {path}")
            body: Any = _pack_path_to_tar_gz(path)
        else:
            body = data

        client = await _shared_client(api_key, domain, request_timeout)
        resp = await client.post(
            "/volumes",
            params={"name": name},
            content=body,
            headers={"Content-Type": content_type},
            timeout=request_timeout,
        )
        return Volume.from_dict(resp.json())

    @staticmethod
    async def empty(
        name: str,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> Volume:
        """Create an empty file-granular volume. 503 if backend not configured."""
        client = await _shared_client(api_key, domain, request_timeout)
        resp = await client.post(
            "/volumes/empty",
            params={"name": name},
            timeout=request_timeout,
        )
        return Volume.from_dict(resp.json())

    @staticmethod
    async def ingest(
        name: str,
        data: Union[
            bytes, BinaryIO, Iterable[bytes], AsyncIterable[bytes], str, "os.PathLike[str]"
        ],
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> Volume:
        """Create a file-granular volume from a gzip tar.gz stream
        (``Content-Type: application/gzip``). 413 quota, 400 bad archive,
        503 backend not configured."""
        if isinstance(data, (str, os.PathLike)):
            path = Path(data)
            if not path.exists():
                raise FileNotFoundError(f"volume source path does not exist: {path}")
            body: Any = _pack_path_to_tar_gz(path)
        else:
            body = data

        client = await _shared_client(api_key, domain, request_timeout)
        resp = await client.post(
            "/volumes/ingest",
            params={"name": name},
            content=body,
            headers={"Content-Type": "application/gzip"},
            timeout=request_timeout,
        )
        return Volume.from_dict(resp.json())

    @staticmethod
    async def snapshot(
        sandbox_id: str,
        path: str,
        name: Optional[str] = None,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> Volume:
        """Capture an arbitrary in-sandbox absolute ``path`` into a NEW volume.

        400 on bad/synthetic path (/proc, /sys, /dev), 404 if not found."""
        client = await _shared_client(api_key, domain, request_timeout)
        params: Dict[str, Any] = {"path": path}
        if name:
            params["name"] = name
        resp = await client.post(
            f"/sandboxes/{sandbox_id}/volumes/snapshot",
            params=params,
            timeout=request_timeout,
        )
        return Volume.from_dict(resp.json())

    @staticmethod
    async def commit(
        sandbox_id: str,
        volume_id: str,
        name: Optional[str] = None,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> Volume:
        """Capture the attached volume's mount path in `sandbox_id` into a NEW volume.

        The source volume is left unchanged. If `name` is None the server names
        the new volume "<source-name>-commit". Returns the new Volume.
        """
        client = await _shared_client(api_key, domain, request_timeout)
        params = {"name": name} if name else None
        resp = await client.post(
            f"/sandboxes/{sandbox_id}/volumes/{volume_id}/commit",
            params=params,
            timeout=request_timeout,
        )
        return Volume.from_dict(resp.json())

    @staticmethod
    async def get(
        volume_id: str,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> Volume:
        client = await _shared_client(api_key, domain, request_timeout)
        resp = await client.get(f"/volumes/{volume_id}", timeout=request_timeout)
        return Volume.from_dict(resp.json())

    @staticmethod
    async def list(
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> List[Volume]:
        client = await _shared_client(api_key, domain, request_timeout)
        resp = await client.get("/volumes", timeout=request_timeout)
        payload = resp.json() or {}
        return [Volume.from_dict(v) for v in payload.get("volumes", [])]

    @staticmethod
    async def download(
        volume_id: str,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> bytes:
        """Download the raw contents of a volume (the tar.gz blob)."""
        client = await _shared_client(api_key, domain, request_timeout)
        resp = await client.get(f"/volumes/{volume_id}/download", timeout=request_timeout)
        return resp.content

    @staticmethod
    async def delete(
        volume_id: str,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> None:
        client = await _shared_client(api_key, domain, request_timeout)
        await client.delete(f"/volumes/{volume_id}", timeout=request_timeout)

    @staticmethod
    def files(
        volume_id: str,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> AsyncVolumeFiles:
        """Return the async files sub-API for ``volume_id``."""
        return AsyncVolumeFiles(
            volume_id, api_key=api_key, domain=domain, request_timeout=request_timeout
        )

    @staticmethod
    def locks(
        volume_id: str,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> AsyncVolumeLocks:
        """Return the async advisory-lock sub-API for ``volume_id``."""
        return AsyncVolumeLocks(
            volume_id, api_key=api_key, domain=domain, request_timeout=request_timeout
        )
