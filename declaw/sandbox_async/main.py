from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union

if TYPE_CHECKING:
    from declaw.security.policy import SecurityPolicy
    from declaw.volumes.main import VolumeAttachment

from declaw.api.async_client import AsyncApiClient, get_shared_async_client
from declaw.connection_config import ConnectionConfig
from declaw.sandbox.commands.models import CommandResult, ProcessInfo
from declaw.sandbox.filesystem.models import EntryInfo, WriteInfo
from declaw.sandbox.main import SandboxBase
from declaw.sandbox.models import (
    SandboxInfo,
    SandboxLifecycle,
    SandboxMetrics,
    SandboxQuery,
    Snapshot,
    SnapshotInfo,
)
from declaw.sandbox.network import ALL_TRAFFIC, SandboxNetworkOpts
from declaw.sandbox_async.commands.command_handle import AsyncCommandHandle
from declaw.sandbox_async.pty import AsyncPty
from declaw.sandbox_async.stdio import AsyncStdio


class AsyncSandbox(SandboxBase):
    """Async Declaw sandbox. Use AsyncSandbox.create() to create a new sandbox."""

    def __init__(
        self,
        sandbox_id: str,
        connection_config: ConnectionConfig,
        client: AsyncApiClient,
        envd_access_token: Optional[str] = None,
        sandbox_domain: Optional[str] = None,
        traffic_access_token: Optional[str] = None,
    ):
        super().__init__(
            sandbox_id=sandbox_id,
            connection_config=connection_config,
            envd_access_token=envd_access_token,
            sandbox_domain=sandbox_domain,
            traffic_access_token=traffic_access_token,
        )
        self._client = client
        self._pty: Optional[AsyncPty] = None
        self._stdio: Optional[AsyncStdio] = None

    @property
    def pty(self) -> AsyncPty:
        """Async PTY module for this sandbox.

        Lazy-constructed so callers who don't need interactive shells
        don't pay any cost. Returns the same instance each call.
        """
        if self._pty is None:
            self._pty = AsyncPty(self._sandbox_id, self._client)
        return self._pty

    @property
    def stdio(self) -> AsyncStdio:
        if self._stdio is None:
            self._stdio = AsyncStdio(self._sandbox_id, self._client)
        return self._stdio

    async def close(self) -> None:
        """Historically closed the async HTTP client; since 1.1.1 the SDK
        maintains a process-wide shared async connection pool (see
        ``declaw.api.async_client.get_shared_async_client``) so per-sandbox
        close no longer tears the pool down. Kept as a no-op — call
        ``declaw.api.async_client.reset_async_shared_clients()`` from the
        same event loop to force socket release."""
        return

    async def __aenter__(self) -> "AsyncSandbox":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        await self.close()

    @classmethod
    async def create(
        cls,
        template: Optional[str] = None,
        timeout: Optional[int] = None,
        metadata: Optional[Dict[str, str]] = None,
        envs: Optional[Dict[str, str]] = None,
        secure: bool = True,
        allow_internet_access: bool = True,
        network: Optional[Union[Dict[str, Any], SandboxNetworkOpts]] = None,
        security: Optional["SecurityPolicy"] = None,
        lifecycle: Optional[SandboxLifecycle] = None,
        volumes: Optional[List[Union[Dict[str, str], "VolumeAttachment"]]] = None,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> AsyncSandbox:
        config = ConnectionConfig(
            api_key=api_key or ConnectionConfig().api_key,
            domain=domain or ConnectionConfig.default_domain(),
            request_timeout=request_timeout,
        )
        client = await get_shared_async_client(config)

        body: Dict[str, Any] = {
            "template": template or cls.default_template,
            "timeout": timeout or cls.default_sandbox_timeout,
            "secure": secure,
        }
        if metadata:
            body["metadata"] = metadata
        if envs:
            body["envs"] = envs
        if not allow_internet_access:
            body["network"] = {"deny_out": [ALL_TRAFFIC]}
        elif network is not None:
            body["network"] = (
                network.to_dict() if isinstance(network, SandboxNetworkOpts) else network
            )
        if security is not None:
            import json as _json

            body["security"] = {"policy_json": _json.dumps(security.to_dict())}
            if security.network and "network" not in body:
                if isinstance(security.network, dict):
                    body["network"] = security.network
                else:
                    body["network"] = security.network.to_dict()
        if lifecycle is not None:
            body["lifecycle"] = lifecycle.to_dict()

        if volumes:
            body["volumes"] = [v.to_dict() if hasattr(v, "to_dict") else dict(v) for v in volumes]

        resp = await client.post("/sandboxes", json=body, timeout=request_timeout)
        data = resp.json()
        return cls(
            sandbox_id=data["sandbox_id"],
            connection_config=config,
            client=client,
            envd_access_token=data.get("envd_access_token"),
            sandbox_domain=data.get("sandbox_domain"),
            traffic_access_token=data.get("traffic_access_token"),
        )

    @classmethod
    async def connect(
        cls,
        sandbox_id: str,
        timeout: Optional[int] = None,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> AsyncSandbox:
        config = ConnectionConfig(
            api_key=api_key or ConnectionConfig().api_key,
            domain=domain or ConnectionConfig.default_domain(),
        )
        client = await get_shared_async_client(config)
        params: Dict[str, Any] = {}
        if timeout is not None:
            params["timeout"] = timeout
        resp = await client.get(f"/sandboxes/{sandbox_id}", params=params, timeout=request_timeout)
        data = resp.json()
        return cls(
            sandbox_id=data["sandbox_id"],
            connection_config=config,
            client=client,
            envd_access_token=data.get("envd_access_token"),
            sandbox_domain=data.get("sandbox_domain"),
            traffic_access_token=data.get("traffic_access_token"),
        )

    async def kill(self, request_timeout: Optional[float] = None, *, wait: bool = False) -> bool:
        path = f"/sandboxes/{self._sandbox_id}"
        if not wait:
            path += "?async=true"
        resp = await self._client.delete(path, timeout=request_timeout)
        body = resp.json()
        if not wait:
            return bool(body.get("queued", True))
        return bool(body.get("killed", False))

    @classmethod
    async def kill_many(
        cls,
        sandbox_ids: List[str],
        *,
        wait: bool = False,
        connection_config: Optional[ConnectionConfig] = None,
        request_timeout: Optional[float] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Kill many sandboxes in a single request. See sync sibling for
        details — same wire shape, async client."""
        if not sandbox_ids:
            return {}
        config = connection_config or ConnectionConfig()
        client = await get_shared_async_client(config)
        path = "/sandboxes/kill-many"
        if not wait:
            path += "?async=true"
        resp = await client.post(
            path,
            json={"sandbox_ids": list(sandbox_ids)},
            timeout=request_timeout,
        )
        body = resp.json()
        return body.get("results", {}) or {}

    @classmethod
    async def kill_by_id(
        cls,
        sandbox_id: str,
        *,
        wait: bool = False,
        connection_config: Optional[ConnectionConfig] = None,
        request_timeout: Optional[float] = None,
    ) -> bool:
        """Kill a sandbox by id without first connecting. See sync
        sibling for details — same wire call, async client."""
        config = connection_config or ConnectionConfig()
        client = await get_shared_async_client(config)
        path = f"/sandboxes/{sandbox_id}"
        if not wait:
            path += "?async=true"
        resp = await client.delete(path, timeout=request_timeout)
        body = resp.json()
        if not wait:
            return bool(body.get("queued", True))
        return bool(body.get("killed", False))

    async def is_running(self, request_timeout: Optional[float] = None) -> bool:
        resp = await self._client.get(
            f"/sandboxes/{self._sandbox_id}/status", timeout=request_timeout
        )
        return bool(resp.json().get("is_running", False))

    async def set_timeout(self, timeout: int, request_timeout: Optional[float] = None) -> None:
        await self._client.patch(
            f"/sandboxes/{self._sandbox_id}/timeout",
            json={"timeout": timeout},
            timeout=request_timeout,
        )

    async def get_info(self, request_timeout: Optional[float] = None) -> SandboxInfo:
        resp = await self._client.get(f"/sandboxes/{self._sandbox_id}", timeout=request_timeout)
        return SandboxInfo.from_dict(resp.json())

    async def get_metrics(
        self,
        start: Optional[datetime.datetime] = None,
        end: Optional[datetime.datetime] = None,
        request_timeout: Optional[float] = None,
    ) -> List[SandboxMetrics]:
        params: Dict[str, Any] = {}
        if start:
            params["start"] = start.isoformat()
        if end:
            params["end"] = end.isoformat()
        resp = await self._client.get(
            f"/sandboxes/{self._sandbox_id}/metrics", params=params, timeout=request_timeout
        )
        return [SandboxMetrics.from_dict(m) for m in (resp.json() or [])]

    # --- Pause / Resume / Snapshots ---

    @staticmethod
    async def list(
        query: Optional["SandboxQuery"] = None,
        limit: Optional[int] = None,
        next_token: Optional[str] = None,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """List sandboxes for the caller (paginated)."""
        config = ConnectionConfig(
            api_key=api_key or ConnectionConfig().api_key,
            domain=domain or ConnectionConfig.default_domain(),
        )
        client = await get_shared_async_client(config)
        params: Dict[str, Any] = {}
        if query:
            params.update(query.to_dict())
        if limit is not None:
            params["limit"] = limit
        if next_token:
            params["next_token"] = next_token
        resp = await client.get("/sandboxes", params=params, timeout=request_timeout)
        data: Dict[str, Any] = resp.json()
        return data

    async def pause(self, request_timeout: Optional[float] = None) -> None:
        await self._client.post(f"/sandboxes/{self._sandbox_id}/pause", timeout=request_timeout)

    async def resume(self, request_timeout: Optional[float] = None) -> None:
        """Resume a previously paused sandbox."""
        await self._client.post(f"/sandboxes/{self._sandbox_id}/resume", timeout=request_timeout)

    async def create_snapshot(self, request_timeout: Optional[float] = None) -> SnapshotInfo:
        resp = await self._client.post(
            f"/sandboxes/{self._sandbox_id}/snapshot", timeout=request_timeout
        )
        return SnapshotInfo.from_dict(resp.json())

    async def snapshot(self, request_timeout: Optional[float] = None) -> Snapshot:
        """Create a manual snapshot of this sandbox.

        Manual snapshots accumulate — every call creates a new persistent
        checkpoint that survives sandbox.kill(). Use AsyncSandbox.list_snapshots()
        to retrieve them and AsyncSandbox.restore(snapshot_id=...) to fork from one.

        Args:
            request_timeout: Optional per-request timeout in seconds.

        Returns:
            Snapshot: metadata about the new snapshot, including its snapshot_id.
        """
        resp = await self._client.post(
            f"/sandboxes/{self._sandbox_id}/snapshot",
            json={},
            timeout=request_timeout,
        )
        return Snapshot.from_dict(resp.json())

    async def list_snapshots(self, request_timeout: Optional[float] = None) -> List[Snapshot]:
        """List all snapshots (periodic + pause + manual) for this sandbox, newest first.

        Args:
            request_timeout: Optional per-request timeout in seconds.

        Returns:
            list[Snapshot]: all snapshots ordered by created_at descending.
        """
        resp = await self._client.get(
            f"/sandboxes/{self._sandbox_id}/snapshots",
            timeout=request_timeout,
        )
        payload = resp.json()
        return [Snapshot.from_dict(s) for s in payload.get("snapshots", [])]

    async def delete_snapshot(
        self,
        snapshot_id: str,
        request_timeout: Optional[float] = None,
    ) -> bool:
        """Delete a single snapshot of this sandbox by ID.

        The snapshot's PG row and S3 blobs (mem / vmstate / overlay) are
        removed. Idempotent: deleting an already-deleted snapshot returns
        True without raising.

        The pause snapshot of a currently-paused sandbox is protected — the
        server returns 409 because deletion would break Resume. Resume or
        kill the sandbox first.

        Args:
            snapshot_id: The snapshot to delete.
            request_timeout: Optional per-request timeout in seconds.

        Returns:
            True on success.
        """
        await self._client.delete(
            f"/sandboxes/{self._sandbox_id}/snapshots/{snapshot_id}",
            timeout=request_timeout,
        )
        return True

    @classmethod
    async def restore(
        cls,
        sandbox_id: str,
        *,
        snapshot_id: Optional[str] = None,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> "AsyncSandbox":
        """Restore a sandbox from a snapshot. The new instance may run on a
        different worker than the original.

        Args:
            sandbox_id: The sandbox to restore.
            snapshot_id: Optional. If omitted, the most recent snapshot
                (preferring pause > periodic > manual) is used.
            api_key: Optional API key override.
            domain: Optional domain override.
            request_timeout: Optional per-request timeout in seconds.

        Returns:
            AsyncSandbox: a usable AsyncSandbox instance connected to the restored sandbox.
        """
        config = ConnectionConfig(
            api_key=api_key or ConnectionConfig().api_key,
            domain=domain or ConnectionConfig.default_domain(),
            request_timeout=request_timeout,
        )
        client = await get_shared_async_client(config)
        params: Dict[str, Any] = {}
        if snapshot_id:
            params["snapshot_id"] = snapshot_id
        await client.post(
            f"/sandboxes/{sandbox_id}/restore",
            params=params,
            timeout=request_timeout,
        )
        return await cls.connect(
            sandbox_id,
            api_key=api_key,
            domain=domain,
            request_timeout=request_timeout,
        )

    # --- Commands ---

    async def run_command(
        self,
        cmd: str,
        background: bool = False,
        envs: Optional[Dict[str, str]] = None,
        user: str = "user",
        cwd: Optional[str] = None,
        on_stdout: Optional[Callable[[str], None]] = None,
        on_stderr: Optional[Callable[[str], None]] = None,
        timeout: Optional[float] = 60,
        request_timeout: Optional[float] = None,
    ) -> Union[CommandResult, AsyncCommandHandle]:
        body: Dict[str, Any] = {"cmd": cmd, "background": background, "user": user}
        if envs:
            body["envs"] = envs
        if cwd:
            body["cwd"] = cwd
        if timeout is not None:
            body["timeout"] = timeout
        resp = await self._client.post(
            f"/sandboxes/{self._sandbox_id}/commands", json=body, timeout=request_timeout
        )
        data = resp.json()
        if background:
            return AsyncCommandHandle(
                pid=data["pid"], sandbox_id=self._sandbox_id, client=self._client
            )
        result = CommandResult.from_dict(data)
        if on_stdout and result.stdout:
            for line in result.stdout.splitlines(keepends=True):
                on_stdout(line)
        if on_stderr and result.stderr:
            for line in result.stderr.splitlines(keepends=True):
                on_stderr(line)
        return result

    async def list_commands(self, request_timeout: Optional[float] = None) -> List[ProcessInfo]:
        resp = await self._client.get(
            f"/sandboxes/{self._sandbox_id}/commands", timeout=request_timeout
        )
        return [ProcessInfo.from_dict(p) for p in (resp.json() or [])]

    async def kill_command(self, pid: int, request_timeout: Optional[float] = None) -> bool:
        resp = await self._client.delete(
            f"/sandboxes/{self._sandbox_id}/commands/{pid}", timeout=request_timeout
        )
        return bool(resp.json().get("killed", False))

    def connect_command(
        self,
        pid: int,
    ) -> AsyncCommandHandle:
        """Reattach to a running background command by pid.

        Returns an :class:`AsyncCommandHandle` scoped to the existing
        process — useful when a prior caller started the command in
        background mode and handed the pid off somewhere durable.
        """
        return AsyncCommandHandle(
            pid=pid,
            sandbox_id=self._sandbox_id,
            client=self._client,
        )

    # --- Filesystem ---

    async def read_file(
        self,
        path: str,
        format: str = "text",
        user: str = "user",
        request_timeout: Optional[float] = None,
    ) -> Union[str, bytearray]:
        resp = await self._client.get(
            f"/sandboxes/{self._sandbox_id}/files",
            params={"path": path, "username": user},
            timeout=request_timeout,
        )
        if format == "bytes":
            return bytearray(resp.content)
        return resp.text

    async def write_file(
        self,
        path: str,
        data: Union[str, bytes],
        user: str = "user",
        request_timeout: Optional[float] = None,
    ) -> WriteInfo:
        """Write ``data`` to ``path`` inside the sandbox.

        ``path`` is the literal absolute path the file will appear at
        inside the guest filesystem — no remapping, no bridge directory,
        no prefix. After this call, the same ``path`` is what commands
        running inside the sandbox should read from. For example, after
        ``await sbx.write_file("/workspace/data.csv", ...)`` a command
        inside the sandbox can ``open("/workspace/data.csv")`` directly.

        Binary uploads (``bytes``) stream via ``PUT /files/raw``; text
        (``str``) goes through the JSON ``POST /files`` endpoint.
        """
        if isinstance(data, bytes):
            resp = await self._client.put(
                f"/sandboxes/{self._sandbox_id}/files/raw",
                params={"path": path, "username": user},
                content=data,
                headers={"Content-Type": "application/octet-stream"},
                timeout=request_timeout,
            )
            return WriteInfo.from_dict(resp.json())
        resp = await self._client.post(
            f"/sandboxes/{self._sandbox_id}/files",
            json={"path": path, "username": user, "data": data},
            timeout=request_timeout,
        )
        return WriteInfo.from_dict(resp.json())

    async def list_files(
        self, path: str, depth: int = 1, user: str = "user", request_timeout: Optional[float] = None
    ) -> List[EntryInfo]:
        resp = await self._client.get(
            f"/sandboxes/{self._sandbox_id}/files/list",
            params={"path": path, "depth": depth, "username": user},
            timeout=request_timeout,
        )
        return [EntryInfo.from_dict(e) for e in (resp.json() or [])]

    async def file_exists(
        self,
        path: str,
        user: str = "user",
        request_timeout: Optional[float] = None,
    ) -> bool:
        resp = await self._client.get(
            f"/sandboxes/{self._sandbox_id}/files/exists",
            params={"path": path, "username": user},
            timeout=request_timeout,
        )
        return bool(resp.json().get("exists", False))

    async def get_file_info(
        self,
        path: str,
        user: str = "user",
        request_timeout: Optional[float] = None,
    ) -> EntryInfo:
        resp = await self._client.get(
            f"/sandboxes/{self._sandbox_id}/files/info",
            params={"path": path, "username": user},
            timeout=request_timeout,
        )
        return EntryInfo.from_dict(resp.json())

    async def remove_file(
        self,
        path: str,
        user: str = "user",
        request_timeout: Optional[float] = None,
    ) -> None:
        await self._client.delete(
            f"/sandboxes/{self._sandbox_id}/files?path={path}&username={user}",
            timeout=request_timeout,
        )

    async def rename_file(
        self,
        old_path: str,
        new_path: str,
        user: str = "user",
        request_timeout: Optional[float] = None,
    ) -> EntryInfo:
        resp = await self._client.patch(
            f"/sandboxes/{self._sandbox_id}/files",
            json={"old_path": old_path, "new_path": new_path, "username": user},
            timeout=request_timeout,
        )
        return EntryInfo.from_dict(resp.json())

    async def make_dir(
        self,
        path: str,
        user: str = "user",
        request_timeout: Optional[float] = None,
    ) -> bool:
        resp = await self._client.post(
            f"/sandboxes/{self._sandbox_id}/files/mkdir",
            json={"path": path, "username": user},
            timeout=request_timeout,
        )
        return bool(resp.json().get("created", False))

    async def write_files(
        self,
        files: List[Any],
        user: str = "user",
        request_timeout: Optional[float] = None,
    ) -> List[WriteInfo]:
        """Batch-write multiple text files in one API call.

        Binary entries are not supported by the batch endpoint — pass
        them one at a time through :meth:`write_file`. Mirrors the
        sync :meth:`Filesystem.write_files` shape but rejects bytes
        rather than silently falling through to per-file PUTs.
        """
        body_files = []
        for f in files:
            data = getattr(f, "data", None)
            if isinstance(data, bytes):
                raise ValueError(
                    "write_files(async) does not support binary data; "
                    "call write_file() for each bytes entry instead."
                )
            body_files.append(f.to_dict() if hasattr(f, "to_dict") else f)
        body = {"files": body_files, "username": user}
        resp = await self._client.post(
            f"/sandboxes/{self._sandbox_id}/files/batch",
            json=body,
            timeout=request_timeout,
        )
        return [WriteInfo.from_dict(w) for w in (resp.json() or [])]

    # --- Commands: stdin + connect reattach ---

    async def send_command_stdin(
        self,
        pid: int,
        data: str,
        request_timeout: Optional[float] = None,
    ) -> None:
        """Send stdin to a running background command."""
        await self._client.post(
            f"/sandboxes/{self._sandbox_id}/commands/{pid}/stdin",
            json={"data": data},
            timeout=request_timeout,
        )
