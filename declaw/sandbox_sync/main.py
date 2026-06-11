from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

if TYPE_CHECKING:
    from declaw.security.policy import SecurityPolicy
    from declaw.volumes.main import VolumeAttachment

from declaw.api.client import ApiClient, get_shared_client
from declaw.connection_config import ConnectionConfig
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
from declaw.sandbox_sync.commands.commands import Commands
from declaw.sandbox_sync.filesystem.filesystem import Filesystem
from declaw.sandbox_sync.pty import Pty
from declaw.sandbox_sync.stdio import Stdio


class Sandbox(SandboxBase):
    """Synchronous Declaw sandbox.

    Use Sandbox.create() to create a new sandbox.
    """

    def __init__(
        self,
        sandbox_id: str,
        connection_config: ConnectionConfig,
        client: ApiClient,
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
        self._commands = Commands(sandbox_id, client)
        self._files = Filesystem(sandbox_id, client)
        self._pty = Pty(sandbox_id, client)
        self._stdio = Stdio(sandbox_id, client)

    def close(self) -> None:
        """Historically closed the HTTP client; since 1.1.1 the SDK maintains
        a process-wide shared connection pool (see
        ``declaw.api.client.get_shared_client``) so per-sandbox close no
        longer tears the pool down. Kept as a no-op for backwards
        compatibility — call ``declaw.api.client.reset_shared_clients()``
        to force socket release."""
        # Intentionally a no-op. Sockets close at process exit.
        return

    def __enter__(self) -> "Sandbox":
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        self.close()

    @property
    def commands(self) -> Commands:
        return self._commands

    @property
    def files(self) -> Filesystem:
        return self._files

    @property
    def pty(self) -> Pty:
        return self._pty

    @property
    def stdio(self) -> Stdio:
        return self._stdio

    @classmethod
    def create(
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
    ) -> Sandbox:
        config = ConnectionConfig(
            api_key=api_key or ConnectionConfig().api_key,
            domain=domain or ConnectionConfig.default_domain(),
            request_timeout=request_timeout,
        )
        client = get_shared_client(config)

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
            if isinstance(network, SandboxNetworkOpts):
                body["network"] = network.to_dict()
            else:
                body["network"] = network

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

        resp = client.post("/sandboxes", json=body, timeout=request_timeout)
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
    def connect(
        cls,
        sandbox_id: str,
        timeout: Optional[int] = None,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> Sandbox:
        config = ConnectionConfig(
            api_key=api_key or ConnectionConfig().api_key,
            domain=domain or ConnectionConfig.default_domain(),
            request_timeout=request_timeout,
        )
        client = get_shared_client(config)

        params: Dict[str, Any] = {}
        if timeout is not None:
            params["timeout"] = timeout

        resp = client.get(f"/sandboxes/{sandbox_id}", params=params, timeout=request_timeout)
        data = resp.json()

        return cls(
            sandbox_id=data["sandbox_id"],
            connection_config=config,
            client=client,
            envd_access_token=data.get("envd_access_token"),
            sandbox_domain=data.get("sandbox_domain"),
            traffic_access_token=data.get("traffic_access_token"),
        )

    def kill(self, request_timeout: Optional[float] = None, *, wait: bool = False) -> bool:
        path = f"/sandboxes/{self._sandbox_id}"
        if not wait:
            path += "?async=true"
        resp = self._client.delete(path, timeout=request_timeout)
        body = resp.json()
        if not wait:
            return bool(body.get("queued", True))
        return bool(body.get("killed", False))

    @classmethod
    def kill_many(
        cls,
        sandbox_ids: List[str],
        *,
        wait: bool = False,
        connection_config: Optional[ConnectionConfig] = None,
        request_timeout: Optional[float] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Kill many sandboxes in a single request.

        Args:
            sandbox_ids: list of sandbox IDs to kill.
            wait: if True, block until each VM's teardown has completed.
                Default is False (server returns 202 once the request is
                queued; cleanup of each VM continues in the background).
            connection_config: optional override; uses the default if
                None.
            request_timeout: per-request timeout in seconds.

        Returns a dict keyed by sandbox_id. Each value is one of
        ``{"killed": True}`` (wait=True success), ``{"queued": True}``
        (default), or ``{"error": "..."}`` (per-id failure).
        """
        if not sandbox_ids:
            return {}
        config = connection_config or ConnectionConfig()
        client = get_shared_client(config)
        path = "/sandboxes/kill-many"
        if not wait:
            path += "?async=true"
        resp = client.post(
            path,
            json={"sandbox_ids": list(sandbox_ids)},
            timeout=request_timeout,
        )
        body = resp.json()
        return body.get("results", {}) or {}

    @classmethod
    def kill_by_id(
        cls,
        sandbox_id: str,
        *,
        wait: bool = False,
        connection_config: Optional[ConnectionConfig] = None,
        request_timeout: Optional[float] = None,
    ) -> bool:
        """Kill a sandbox by id without first connecting.

        Sends a single ``DELETE /sandboxes/:id?async=true`` (or without
        the query param when ``wait=True``) and skips the metadata
        fetch a ``Sandbox.connect(id).kill()`` flow would otherwise
        pay. Useful for bulk-cleanup paths that only have the id.
        """
        config = connection_config or ConnectionConfig()
        client = get_shared_client(config)
        path = f"/sandboxes/{sandbox_id}"
        if not wait:
            path += "?async=true"
        resp = client.delete(path, timeout=request_timeout)
        body = resp.json()
        if not wait:
            return bool(body.get("queued", True))
        return bool(body.get("killed", False))

    def is_running(self, request_timeout: Optional[float] = None) -> bool:
        resp = self._client.get(
            f"/sandboxes/{self._sandbox_id}/status",
            timeout=request_timeout,
        )
        return bool(resp.json().get("is_running", False))

    def set_timeout(self, timeout: int, request_timeout: Optional[float] = None) -> None:
        self._client.patch(
            f"/sandboxes/{self._sandbox_id}/timeout",
            json={"timeout": timeout},
            timeout=request_timeout,
        )

    def get_info(self, request_timeout: Optional[float] = None) -> SandboxInfo:
        resp = self._client.get(
            f"/sandboxes/{self._sandbox_id}",
            timeout=request_timeout,
        )
        return SandboxInfo.from_dict(resp.json())

    def get_metrics(
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
        resp = self._client.get(
            f"/sandboxes/{self._sandbox_id}/metrics",
            params=params,
            timeout=request_timeout,
        )
        return [SandboxMetrics.from_dict(m) for m in (resp.json() or [])]

    @staticmethod
    def list(
        query: Optional[SandboxQuery] = None,
        limit: Optional[int] = None,
        next_token: Optional[str] = None,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        config = ConnectionConfig(
            api_key=api_key or ConnectionConfig().api_key,
            domain=domain or ConnectionConfig.default_domain(),
        )
        client = get_shared_client(config)
        params: Dict[str, Any] = {}
        if query:
            params.update(query.to_dict())
        if limit is not None:
            params["limit"] = limit
        if next_token:
            params["next_token"] = next_token
        resp = client.get("/sandboxes", params=params, timeout=request_timeout)
        data: Dict[str, Any] = resp.json()
        return data

    # --- Pause / Resume / Snapshots ---

    def pause(self, request_timeout: Optional[float] = None) -> None:
        self._client.post(
            f"/sandboxes/{self._sandbox_id}/pause",
            timeout=request_timeout,
        )

    def resume(self, request_timeout: Optional[float] = None) -> None:
        self._client.post(
            f"/sandboxes/{self._sandbox_id}/resume",
            timeout=request_timeout,
        )

    def create_snapshot(self, request_timeout: Optional[float] = None) -> SnapshotInfo:
        resp = self._client.post(
            f"/sandboxes/{self._sandbox_id}/snapshot",
            timeout=request_timeout,
        )
        return SnapshotInfo.from_dict(resp.json())

    def snapshot(self, request_timeout: Optional[float] = None) -> Snapshot:
        """Create a manual snapshot of this sandbox.

        Manual snapshots accumulate — every call creates a new persistent
        checkpoint that survives sandbox.kill(). Use Sandbox.list_snapshots()
        to retrieve them and Sandbox.restore(snapshot_id=...) to fork from one.

        Args:
            request_timeout: Optional per-request timeout in seconds.

        Returns:
            Snapshot: metadata about the new snapshot, including its snapshot_id.
        """
        resp = self._client.post(
            f"/sandboxes/{self._sandbox_id}/snapshot",
            json={},
            timeout=request_timeout,
        )
        return Snapshot.from_dict(resp.json())

    def list_snapshots(self, request_timeout: Optional[float] = None) -> List[Snapshot]:
        """List all snapshots (periodic + pause + manual) for this sandbox, newest first.

        Args:
            request_timeout: Optional per-request timeout in seconds.

        Returns:
            list[Snapshot]: all snapshots ordered by created_at descending.
        """
        resp = self._client.get(
            f"/sandboxes/{self._sandbox_id}/snapshots",
            timeout=request_timeout,
        )
        payload = resp.json()
        return [Snapshot.from_dict(s) for s in payload.get("snapshots", [])]

    def delete_snapshot(
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
        self._client.delete(
            f"/sandboxes/{self._sandbox_id}/snapshots/{snapshot_id}",
            timeout=request_timeout,
        )
        return True

    @classmethod
    def restore(
        cls,
        sandbox_id: str,
        *,
        snapshot_id: Optional[str] = None,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> "Sandbox":
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
            Sandbox: a usable Sandbox instance connected to the restored sandbox.
        """
        config = ConnectionConfig(
            api_key=api_key or ConnectionConfig().api_key,
            domain=domain or ConnectionConfig.default_domain(),
            request_timeout=request_timeout,
        )
        client = get_shared_client(config)
        params: Dict[str, Any] = {}
        if snapshot_id:
            params["snapshot_id"] = snapshot_id
        client.post(
            f"/sandboxes/{sandbox_id}/restore",
            params=params,
            timeout=request_timeout,
        )
        return cls.connect(
            sandbox_id,
            api_key=api_key,
            domain=domain,
            request_timeout=request_timeout,
        )
