"""Volumes: tenant-owned blobs you attach to one or many sandboxes.

Two volume backends exist server-side:

- **tarball** (classic): a single gzip-tar blob. Created with ``Volumes.create``;
  hydrated into the sandbox filesystem at boot (``mode="copy"``).
- **file-granular**: an object-per-file store you can read/write/list/stat
  remotely (``Volumes.empty`` / ``Volumes.ingest``), live-mount into a sandbox
  (``mode="mount"`` / ``"mount-ro"``), do CAS writes against, and hold advisory
  locks over.

On ``Sandbox.create(volumes=[...])`` an attachment names a volume, a mount path,
and (optionally) a ``mode`` and ``subpath``:

- ``mode``: ``copy`` (default — hydrate at boot), ``mount`` (rw live), ``mount-ro``
  (read-only live).
- ``subpath``: relative path within the volume. LIVE-MOUNT ONLY (the server
  rejects ``subpath`` on a ``copy`` attachment).

Phase 1 tarball contract (``Volumes.create``):
- The blob body must be a gzip-compressed tar archive (tar.gz, ``application/gzip``).
- Only regular files are materialized inside the sandbox; symlinks, hardlinks
  and device nodes are dropped on the server.
- Upload body is capped at 500 MiB (same as /files/raw).
"""

from __future__ import annotations

import io
import os
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterable, List, Optional, Union

from declaw.api.client import ApiClient, get_shared_client
from declaw.connection_config import ConnectionConfig


@dataclass
class VolumeAttachment:
    """A volume attachment passed to ``Sandbox.create(volumes=...)``.

    ``mode`` and ``subpath`` are optional. ``mode`` defaults to ``"copy"``
    (hydrate-at-boot) and is omitted from the wire when empty/``copy``.
    ``subpath`` is live-mount only and omitted when empty.
    """

    volume_id: str
    mount_path: str
    mode: Optional[str] = None
    subpath: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"volume_id": self.volume_id, "mount_path": self.mount_path}
        # Omit mode when empty or the default "copy" so the wire stays minimal.
        if self.mode and self.mode != "copy":
            out["mode"] = self.mode
        if self.subpath:
            out["subpath"] = self.subpath
        return out


@dataclass
class Volume:
    """Server-side metadata for a single volume."""

    volume_id: str
    owner_id: str
    name: str
    blob_key: str
    size_bytes: int
    content_type: str
    created_at: str
    metadata: Dict[str, str] = field(default_factory=dict)
    backend: str = ""
    quota_bytes: int = 0
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Volume":
        return cls(
            volume_id=data["volume_id"],
            owner_id=data.get("owner_id", ""),
            name=data.get("name", ""),
            blob_key=data.get("blob_key", ""),
            size_bytes=int(data.get("size_bytes", 0)),
            content_type=data.get("content_type", ""),
            created_at=data.get("created_at", ""),
            metadata=data.get("metadata") or {},
            backend=data.get("backend", ""),
            quota_bytes=int(data.get("quota_bytes", 0)),
            updated_at=data.get("updated_at", ""),
        )

    def attach(
        self,
        mount_path: str,
        *,
        mode: Optional[str] = None,
        subpath: Optional[str] = None,
    ) -> VolumeAttachment:
        """Shortcut: ``vol.attach('/data')`` -> ``VolumeAttachment(...)``.

        Pass ``mode="mount"``/``"mount-ro"`` for a live mount and ``subpath``
        to mount a relative path within the volume (live-mount only).
        """
        return VolumeAttachment(
            volume_id=self.volume_id, mount_path=mount_path, mode=mode, subpath=subpath
        )


@dataclass
class FileEntry:
    """A directory/stat entry returned by the file-granular files API."""

    name: str
    path: str
    is_dir: bool
    size: int
    mod_time: str
    mode: int
    # Only populated by ``info`` — the CAS token to round-trip into ``write(if_version=...)``.
    version: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileEntry":
        return cls(
            name=data.get("name", ""),
            path=data.get("path", ""),
            is_dir=bool(data.get("is_dir", False)),
            size=int(data.get("size", 0)),
            mod_time=data.get("mod_time", ""),
            mode=int(data.get("mode", 0)),
            version=data.get("version", ""),
        )


def _pack_path_to_tar_gz(path: Path) -> bytes:
    """Tar+gzip a single file or directory into memory.

    Used when the caller passes a filesystem path to Volumes.create. For
    larger trees the caller should pre-build the tarball themselves and
    pass the bytes or a file handle directly — the in-memory encode is
    only a convenience for small datasets.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(path, arcname=path.name if path.is_file() else ".")
    return buf.getvalue()


def _shared_sync_client(
    api_key: Optional[str] = None,
    domain: Optional[str] = None,
    request_timeout: Optional[float] = None,
) -> ApiClient:
    """Return a process-wide ApiClient keyed by config. Shared — do not
    ``close()`` it; the cache in ``declaw.api.client`` manages lifetime."""
    config = ConnectionConfig(
        api_key=api_key or ConnectionConfig().api_key,
        domain=domain or ConnectionConfig.default_domain(),
        request_timeout=request_timeout,
    )
    return get_shared_client(config)


class VolumeFiles:
    """Files sub-API for a single file-granular volume.

    Obtain via ``Volumes.files(volume_id)``. Every method targets
    ``/volumes/{volume_id}/files/...``. These only work on file-granular
    volumes (409 if the volume is on the tarball backend).
    """

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

    def _client(self) -> ApiClient:
        return _shared_sync_client(self._api_key, self._domain, self._request_timeout)

    def write(
        self,
        path: str,
        data: Union[bytes, BinaryIO, Iterable[bytes]],
        *,
        if_version: Optional[str] = None,
    ) -> str:
        """Write raw bytes to ``path``. Returns the written path.

        Pass ``if_version`` (from ``info(path).version``) for an optimistic
        CAS write — a ``ConflictException`` (HTTP 409) means the file changed
        and you should re-read and retry. Omit for an unconditional write.
        """
        params: Dict[str, Any] = {"path": path}
        if if_version is not None:
            params["if_version"] = if_version
        resp = self._client().put(
            f"/volumes/{self.volume_id}/files/raw",
            params=params,
            content=data,
            headers={"Content-Type": "application/octet-stream"},
            timeout=self._request_timeout,
        )
        return str((resp.json() or {}).get("path", path))

    def read(self, path: str) -> bytes:
        """Read ``path`` and return its raw bytes."""
        resp = self._client().get(
            f"/volumes/{self.volume_id}/files/raw",
            params={"path": path},
            timeout=self._request_timeout,
        )
        return resp.content

    def list(self, path: str = "/") -> List[FileEntry]:
        """List entries under directory ``path``."""
        resp = self._client().get(
            f"/volumes/{self.volume_id}/files/list",
            params={"path": path},
            timeout=self._request_timeout,
        )
        payload = resp.json() or {}
        return [FileEntry.from_dict(e) for e in payload.get("entries", [])]

    def info(self, path: str) -> FileEntry:
        """Stat ``path``. The returned ``FileEntry.version`` is the CAS token
        to round-trip into ``write(if_version=...)``."""
        resp = self._client().get(
            f"/volumes/{self.volume_id}/files/info",
            params={"path": path},
            timeout=self._request_timeout,
        )
        return FileEntry.from_dict(resp.json() or {})

    def exists(self, path: str) -> bool:
        """Return whether ``path`` exists."""
        resp = self._client().get(
            f"/volumes/{self.volume_id}/files/exists",
            params={"path": path},
            timeout=self._request_timeout,
        )
        return bool((resp.json() or {}).get("exists", False))

    def remove(self, path: str, *, recursive: bool = False) -> None:
        """Remove ``path``. Pass ``recursive=True`` to remove a directory tree."""
        self._client().delete(
            f"/volumes/{self.volume_id}/files",
            params={"path": path, "recursive": "true" if recursive else "false"},
            timeout=self._request_timeout,
        )

    def rename(self, old_path: str, new_path: str) -> Dict[str, str]:
        """Rename/move ``old_path`` to ``new_path``."""
        resp = self._client().patch(
            f"/volumes/{self.volume_id}/files",
            json={"old_path": old_path, "new_path": new_path},
            timeout=self._request_timeout,
        )
        return resp.json() or {}

    def mkdir(self, path: str) -> str:
        """Create directory ``path``. Returns the created path."""
        resp = self._client().post(
            f"/volumes/{self.volume_id}/files/mkdir",
            json={"path": path},
            timeout=self._request_timeout,
        )
        return str((resp.json() or {}).get("path", path))


class VolumeLocks:
    """Advisory-lock (lease) sub-API for a single volume.

    Obtain via ``Volumes.locks(volume_id)``. Locks are advisory over a
    ``(volume, path)`` pair; ``acquire`` returns a token you must present to
    ``renew``/``release``.
    """

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

    def _client(self) -> ApiClient:
        return _shared_sync_client(self._api_key, self._domain, self._request_timeout)

    def acquire(self, path: str, *, ttl_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Acquire the lock over ``path``. Returns
        ``{"token", "ttl_seconds", "expires_at"}``. A ``ConflictException``
        (409) means it is already held."""
        body: Dict[str, Any] = {"path": path}
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        resp = self._client().post(
            f"/volumes/{self.volume_id}/locks",
            json=body,
            timeout=self._request_timeout,
        )
        return resp.json() or {}

    def release(self, path: str, token: str) -> bool:
        """Release the lock. Returns ``released``. 409 if you are not the holder."""
        resp = self._client().delete(
            f"/volumes/{self.volume_id}/locks",
            json={"path": path, "token": token},
            timeout=self._request_timeout,
        )
        return bool((resp.json() or {}).get("released", False))

    def renew(self, path: str, token: str, *, ttl_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Renew the lock. 409 if you are not the holder."""
        body: Dict[str, Any] = {"path": path, "token": token}
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        resp = self._client().post(
            f"/volumes/{self.volume_id}/locks/renew",
            json=body,
            timeout=self._request_timeout,
        )
        return resp.json() or {}

    def status(self, path: str) -> Dict[str, Any]:
        """Return ``{"held": bool, "expires_in_ms": int}`` for ``path``."""
        resp = self._client().get(
            f"/volumes/{self.volume_id}/locks",
            params={"path": path},
            timeout=self._request_timeout,
        )
        return resp.json() or {}


class Volumes:
    """Sync client for the /volumes CRUD API."""

    @staticmethod
    def _client(
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> ApiClient:
        """Return a process-wide ApiClient keyed by config. Shared — do
        not ``close()`` it; the cache in ``declaw.api.client`` manages
        lifetime."""
        return _shared_sync_client(api_key, domain, request_timeout)

    @staticmethod
    def create(
        name: str,
        data: Union[bytes, BinaryIO, Iterable[bytes], str, "os.PathLike[str]"],
        *,
        content_type: str = "application/gzip",
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> Volume:
        """Upload a tarball and return the registered Volume.

        `data` may be:
            - bytes: uploaded as-is;
            - a file-like object open in binary mode: streamed as-is;
            - an iterable of bytes chunks: streamed as-is;
            - a path-like pointing to a file or directory: packed into a
              tar.gz in memory and uploaded.
        """
        if isinstance(data, (str, os.PathLike)):
            path = Path(data)
            if not path.exists():
                raise FileNotFoundError(f"volume source path does not exist: {path}")
            body: Union[bytes, BinaryIO, Iterable[bytes]] = _pack_path_to_tar_gz(path)
        else:
            body = data

        client = Volumes._client(api_key=api_key, domain=domain, request_timeout=request_timeout)
        resp = client.post(
            "/volumes",
            params={"name": name},
            content=body,
            headers={"Content-Type": content_type},
            timeout=request_timeout,
        )
        return Volume.from_dict(resp.json())

    @staticmethod
    def empty(
        name: str,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> Volume:
        """Create an empty file-granular volume. 503 if the file-granular
        backend is not configured."""
        client = Volumes._client(api_key=api_key, domain=domain, request_timeout=request_timeout)
        resp = client.post(
            "/volumes/empty",
            params={"name": name},
            timeout=request_timeout,
        )
        return Volume.from_dict(resp.json())

    @staticmethod
    def ingest(
        name: str,
        data: Union[bytes, BinaryIO, Iterable[bytes], str, "os.PathLike[str]"],
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> Volume:
        """Create a file-granular volume from a gzip tar.gz stream.

        `data` follows the same rules as ``create``. The body is sent with
        ``Content-Type: application/gzip``. 413 on quota, 400 on bad archive,
        503 if the backend is not configured.
        """
        if isinstance(data, (str, os.PathLike)):
            path = Path(data)
            if not path.exists():
                raise FileNotFoundError(f"volume source path does not exist: {path}")
            body: Union[bytes, BinaryIO, Iterable[bytes]] = _pack_path_to_tar_gz(path)
        else:
            body = data

        client = Volumes._client(api_key=api_key, domain=domain, request_timeout=request_timeout)
        resp = client.post(
            "/volumes/ingest",
            params={"name": name},
            content=body,
            headers={"Content-Type": "application/gzip"},
            timeout=request_timeout,
        )
        return Volume.from_dict(resp.json())

    @staticmethod
    def snapshot(
        sandbox_id: str,
        path: str,
        name: Optional[str] = None,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> Volume:
        """Capture an arbitrary in-sandbox ``path`` into a NEW volume.

        ``path`` must be an absolute in-sandbox path. ``name`` defaults to
        "snapshot" server-side. 400 on a bad/synthetic path (/proc, /sys,
        /dev), 404 if the sandbox is not found.
        """
        client = Volumes._client(api_key=api_key, domain=domain, request_timeout=request_timeout)
        params: Dict[str, Any] = {"path": path}
        if name:
            params["name"] = name
        resp = client.post(
            f"/sandboxes/{sandbox_id}/volumes/snapshot",
            params=params,
            timeout=request_timeout,
        )
        return Volume.from_dict(resp.json())

    @staticmethod
    def commit(
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
        client = Volumes._client(api_key=api_key, domain=domain, request_timeout=request_timeout)
        params = {"name": name} if name else None
        resp = client.post(
            f"/sandboxes/{sandbox_id}/volumes/{volume_id}/commit",
            params=params,
            timeout=request_timeout,
        )
        return Volume.from_dict(resp.json())

    @staticmethod
    def get(
        volume_id: str,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> Volume:
        client = Volumes._client(api_key=api_key, domain=domain, request_timeout=request_timeout)
        resp = client.get(f"/volumes/{volume_id}", timeout=request_timeout)
        return Volume.from_dict(resp.json())

    @staticmethod
    def list(
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> List[Volume]:
        client = Volumes._client(api_key=api_key, domain=domain, request_timeout=request_timeout)
        resp = client.get("/volumes", timeout=request_timeout)
        payload = resp.json() or {}
        return [Volume.from_dict(v) for v in payload.get("volumes", [])]

    @staticmethod
    def download(
        volume_id: str,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> bytes:
        """Download the raw contents of a volume (the tar.gz blob)."""
        client = Volumes._client(api_key=api_key, domain=domain, request_timeout=request_timeout)
        resp = client.get(f"/volumes/{volume_id}/download", timeout=request_timeout)
        return resp.content

    @staticmethod
    def delete(
        volume_id: str,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> None:
        client = Volumes._client(api_key=api_key, domain=domain, request_timeout=request_timeout)
        client.delete(f"/volumes/{volume_id}", timeout=request_timeout)

    @staticmethod
    def files(
        volume_id: str,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> VolumeFiles:
        """Return the files sub-API for ``volume_id`` (file-granular volumes)."""
        return VolumeFiles(
            volume_id, api_key=api_key, domain=domain, request_timeout=request_timeout
        )

    @staticmethod
    def locks(
        volume_id: str,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> VolumeLocks:
        """Return the advisory-lock sub-API for ``volume_id``."""
        return VolumeLocks(
            volume_id, api_key=api_key, domain=domain, request_timeout=request_timeout
        )
