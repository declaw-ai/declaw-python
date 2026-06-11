from __future__ import annotations

from typing import Any, Dict, List, Optional

from declaw.api.async_client import AsyncApiClient
from declaw.sandbox.models import SandboxInfo, SandboxQuery, SnapshotInfo


class AsyncSandboxPaginator:
    """Async paginator for listing sandboxes."""

    def __init__(
        self,
        client: AsyncApiClient,
        query: Optional[SandboxQuery] = None,
        limit: Optional[int] = None,
    ):
        self._client = client
        self._query = query
        self._limit = limit
        self._next_token: Optional[str] = ""
        self._exhausted = False

    @property
    def has_next(self) -> bool:
        return not self._exhausted

    async def next_items(self) -> List[SandboxInfo]:
        if self._exhausted:
            raise RuntimeError("No more pages available. Check has_next before calling next_items.")
        params: Dict[str, Any] = {}
        if self._query:
            params.update(self._query.to_dict())
        if self._limit is not None:
            params["limit"] = self._limit
        if self._next_token:
            params["next_token"] = self._next_token
        resp = await self._client.get("/sandboxes", params=params)
        data = resp.json()
        self._next_token = data.get("next_token")
        if not self._next_token:
            self._exhausted = True
        return [SandboxInfo.from_dict(s) for s in data.get("sandboxes", [])]


class AsyncSnapshotPaginator:
    """Async paginator for listing snapshots."""

    def __init__(
        self, client: AsyncApiClient, sandbox_id: Optional[str] = None, limit: Optional[int] = None
    ):
        self._client = client
        self._sandbox_id = sandbox_id
        self._limit = limit
        self._next_token: Optional[str] = ""
        self._exhausted = False

    @property
    def has_next(self) -> bool:
        return not self._exhausted

    async def next_items(self) -> List[SnapshotInfo]:
        if self._exhausted:
            raise RuntimeError("No more pages available. Check has_next before calling next_items.")
        params: Dict[str, Any] = {}
        if self._sandbox_id:
            params["sandbox_id"] = self._sandbox_id
        if self._limit is not None:
            params["limit"] = self._limit
        if self._next_token:
            params["next_token"] = self._next_token
        resp = await self._client.get("/snapshots", params=params)
        data = resp.json()
        self._next_token = data.get("next_token")
        if not self._next_token:
            self._exhausted = True
        return [SnapshotInfo.from_dict(s) for s in data.get("snapshots", [])]
