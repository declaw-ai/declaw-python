from __future__ import annotations

from typing import IO, Any, Dict, Iterator, List, Literal, Optional, Union, overload

from declaw.api.client import ApiClient
from declaw.sandbox.filesystem.models import EntryInfo, WriteEntry, WriteInfo
from declaw.sandbox_sync.filesystem.watch_handle import WatchHandle

DEFAULT_USER = "user"


class Filesystem:
    """Module for interacting with the sandbox filesystem."""

    def __init__(self, sandbox_id: str, client: ApiClient):
        self._sandbox_id = sandbox_id
        self._client = client

    @overload
    def read(
        self,
        path: str,
        format: Literal["text"] = ...,
        user: str = ...,
        request_timeout: Optional[float] = ...,
    ) -> str: ...
    @overload
    def read(
        self,
        path: str,
        format: Literal["bytes"],
        user: str = ...,
        request_timeout: Optional[float] = ...,
    ) -> bytearray: ...
    @overload
    def read(
        self,
        path: str,
        format: Literal["stream"],
        user: str = ...,
        request_timeout: Optional[float] = ...,
    ) -> Iterator[bytes]: ...

    def read(
        self,
        path: str,
        format: str = "text",
        user: str = DEFAULT_USER,
        request_timeout: Optional[float] = None,
    ) -> Union[str, bytearray, Iterator[bytes]]:
        params: Dict[str, Any] = {"path": path, "username": user}
        headers = {}
        if format == "bytes":
            headers["Accept"] = "application/octet-stream"
        elif format == "stream":
            headers["Accept"] = "application/octet-stream"
        else:
            headers["Accept"] = "text/plain"

        resp = self._client.get(
            f"/sandboxes/{self._sandbox_id}/files",
            params=params,
            timeout=request_timeout,
        )

        if format == "bytes":
            return bytearray(resp.content)
        elif format == "stream":
            return iter([resp.content])
        return resp.text

    def write(
        self,
        path: str,
        data: Union[str, bytes, IO[Any]],
        user: str = DEFAULT_USER,
        request_timeout: Optional[float] = None,
    ) -> WriteInfo:
        """Write ``data`` to ``path`` inside the sandbox.

        ``path`` is the literal absolute path the file will appear at
        inside the guest filesystem — no remapping, no bridge directory,
        no prefix. After this call, the same ``path`` is what commands
        running inside the sandbox should read from. For example, after
        ``sbx.files.write("/workspace/data.csv", ...)`` a command inside
        the sandbox can ``open("/workspace/data.csv")`` directly.

        Binary uploads (``bytes``) stream via ``PUT /files/raw``; text
        (``str``) goes through the JSON ``POST /files`` endpoint.
        """
        if not isinstance(data, (str, bytes)):
            data = data.read()
        if isinstance(data, bytes):
            resp = self._client.put(
                f"/sandboxes/{self._sandbox_id}/files/raw",
                params={"path": path, "username": user},
                content=data,
                headers={"Content-Type": "application/octet-stream"},
                timeout=request_timeout,
            )
            return WriteInfo.from_dict(resp.json())
        resp = self._client.post(
            f"/sandboxes/{self._sandbox_id}/files",
            json={"path": path, "username": user, "data": data},
            timeout=request_timeout,
        )
        return WriteInfo.from_dict(resp.json())

    def write_files(
        self,
        files: List[WriteEntry],
        user: str = DEFAULT_USER,
        request_timeout: Optional[float] = None,
    ) -> List[WriteInfo]:
        # The batch endpoint is JSON-only and can't carry binary. Partition entries:
        # str entries go through POST /files/batch; bytes entries go through
        # PUT /files/raw individually. Results are merged back in input order.
        results: List[Optional[WriteInfo]] = [None] * len(files)
        str_indices = [i for i, f in enumerate(files) if isinstance(f.data, str)]
        bytes_indices = [i for i, f in enumerate(files) if isinstance(f.data, bytes)]

        if str_indices:
            body = {
                "files": [files[i].to_dict() for i in str_indices],
                "username": user,
            }
            resp = self._client.post(
                f"/sandboxes/{self._sandbox_id}/files/batch",
                json=body,
                timeout=request_timeout,
            )
            for i, w in zip(str_indices, resp.json() or []):
                results[i] = WriteInfo.from_dict(w)

        for i in bytes_indices:
            entry = files[i]
            assert isinstance(entry.data, bytes)
            resp = self._client.put(
                f"/sandboxes/{self._sandbox_id}/files/raw",
                params={"path": entry.path, "username": user},
                content=entry.data,
                headers={"Content-Type": "application/octet-stream"},
                timeout=request_timeout,
            )
            results[i] = WriteInfo.from_dict(resp.json())

        return [r for r in results if r is not None]

    def list(
        self,
        path: str,
        depth: Optional[int] = 1,
        user: str = DEFAULT_USER,
        request_timeout: Optional[float] = None,
    ) -> List[EntryInfo]:
        params: Dict[str, Any] = {"path": path, "username": user}
        if depth is not None:
            params["depth"] = depth
        resp = self._client.get(
            f"/sandboxes/{self._sandbox_id}/files/list",
            params=params,
            timeout=request_timeout,
        )
        return [EntryInfo.from_dict(e) for e in (resp.json() or [])]

    def exists(
        self,
        path: str,
        user: str = DEFAULT_USER,
        request_timeout: Optional[float] = None,
    ) -> bool:
        resp = self._client.get(
            f"/sandboxes/{self._sandbox_id}/files/exists",
            params={"path": path, "username": user},
            timeout=request_timeout,
        )
        return bool(resp.json().get("exists", False))

    def get_info(
        self,
        path: str,
        user: str = DEFAULT_USER,
        request_timeout: Optional[float] = None,
    ) -> EntryInfo:
        resp = self._client.get(
            f"/sandboxes/{self._sandbox_id}/files/info",
            params={"path": path, "username": user},
            timeout=request_timeout,
        )
        return EntryInfo.from_dict(resp.json())

    def remove(
        self,
        path: str,
        user: str = DEFAULT_USER,
        request_timeout: Optional[float] = None,
    ) -> None:
        self._client.delete(
            f"/sandboxes/{self._sandbox_id}/files?path={path}&username={user}",
            timeout=request_timeout,
        )

    def rename(
        self,
        old_path: str,
        new_path: str,
        user: str = DEFAULT_USER,
        request_timeout: Optional[float] = None,
    ) -> EntryInfo:
        resp = self._client.patch(
            f"/sandboxes/{self._sandbox_id}/files",
            json={"old_path": old_path, "new_path": new_path, "username": user},
            timeout=request_timeout,
        )
        return EntryInfo.from_dict(resp.json())

    def make_dir(
        self,
        path: str,
        user: str = DEFAULT_USER,
        request_timeout: Optional[float] = None,
    ) -> bool:
        resp = self._client.post(
            f"/sandboxes/{self._sandbox_id}/files/mkdir",
            json={"path": path, "username": user},
            timeout=request_timeout,
        )
        return bool(resp.json().get("created", False))

    def watch_dir(
        self,
        path: str,
        user: str = DEFAULT_USER,
        request_timeout: Optional[float] = None,
        recursive: bool = False,
    ) -> WatchHandle:
        self._client.post(
            f"/sandboxes/{self._sandbox_id}/files/watch",
            json={"path": path, "username": user, "recursive": recursive},
            timeout=request_timeout,
        )
        return WatchHandle()
