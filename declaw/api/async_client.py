from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Tuple

import httpx

from declaw.api.client import _connection_limits
from declaw.api.client import _RawBody as _RawBody  # re-use the sync type alias
from declaw.connection_config import ConnectionConfig
from declaw.exceptions import (
    AuthenticationException,
    ConflictException,
    InsufficientBalanceException,
    InvalidArgumentException,
    NotEnoughSpaceException,
    NotFoundException,
    RateLimitException,
    SandboxException,
    TimeoutException,
)

_STATUS_MAP = {
    400: InvalidArgumentException,
    401: AuthenticationException,
    403: AuthenticationException,
    404: NotFoundException,
    408: TimeoutException,
    409: ConflictException,
    413: NotEnoughSpaceException,
    422: InvalidArgumentException,
    402: InsufficientBalanceException,
    429: RateLimitException,
}


class AsyncApiClient:
    """Async HTTP client for the Declaw API."""

    def __init__(
        self,
        config: Optional[ConnectionConfig] = None,
        *,
        max_retries: int = 3,
        retry_delay: float = 0.5,
    ):
        self.config = config or ConnectionConfig()
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._client = httpx.AsyncClient(
            base_url=self.config.api_url or "",
            timeout=self.config.request_timeout or 30.0,
            headers=self._base_headers(),
            http2=True,
            limits=_connection_limits(),
        )
        self._stream_client = httpx.AsyncClient(
            base_url=self.config.api_url or "",
            timeout=None,
            headers=self._base_headers(),
            http2=True,
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=16),
        )

    def _base_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        exc_cls = _STATUS_MAP.get(response.status_code, SandboxException)
        try:
            body = response.json()
            message = body.get("message", body.get("error", response.text))
        except Exception:
            message = response.text
        if response.status_code == 429:
            retry_after: Optional[float] = None
            raw = response.headers.get("Retry-After")
            if raw is not None:
                try:
                    retry_after = float(raw)
                except ValueError:
                    pass
            raise RateLimitException(f"HTTP 429: {message}", retry_after=retry_after)
        if response.status_code == 402:
            try:
                wallet_type = response.json().get("wallet_type", "")
            except Exception:
                wallet_type = ""
            raise InsufficientBalanceException(f"HTTP 402: {message}", wallet_type=wallet_type)
        raise exc_cls(f"HTTP {response.status_code}: {message}")

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Optional[Dict[str, Any]] = None,
        content: Optional[_RawBody] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        last_exc: Optional[Exception] = None
        # A streaming/iterator body is consumed on the first send and would replay
        # as empty on a retry, silently truncating an upload. Only retry when the
        # body is replayable (None or a fully-materialized bytes/str payload).
        replayable = content is None or isinstance(content, (bytes, bytearray, str))
        for attempt in range(self._max_retries):
            try:
                response = await self._client.request(
                    method,
                    path,
                    json=json,
                    params=params,
                    content=content,
                    headers=headers,
                    timeout=timeout,
                )
                if response.status_code >= 500 and attempt < self._max_retries - 1 and replayable:
                    await asyncio.sleep(self._retry_delay * (attempt + 1))
                    continue
                self._raise_for_status(response)
                return response
            except (httpx.ConnectError, httpx.ReadTimeout) as e:
                last_exc = e
                if attempt < self._max_retries - 1 and replayable:
                    await asyncio.sleep(self._retry_delay * (attempt + 1))
                    continue
                raise TimeoutException(f"Connection failed after {self._max_retries} retries: {e}")
        raise SandboxException(f"Request failed: {last_exc}")

    async def get(
        self, path: str, *, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None
    ) -> httpx.Response:
        return await self._request_with_retry("GET", path, params=params, timeout=timeout)

    async def post(
        self,
        path: str,
        *,
        json: Any = None,
        params: Optional[Dict[str, Any]] = None,
        content: Optional[_RawBody] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        return await self._request_with_retry(
            "POST",
            path,
            json=json,
            params=params,
            content=content,
            headers=headers,
            timeout=timeout,
        )

    async def patch(
        self, path: str, *, json: Any = None, timeout: Optional[float] = None
    ) -> httpx.Response:
        return await self._request_with_retry("PATCH", path, json=json, timeout=timeout)

    async def delete(
        self,
        path: str,
        *,
        json: Any = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        return await self._request_with_retry(
            "DELETE", path, json=json, params=params, timeout=timeout
        )

    async def put(
        self,
        path: str,
        *,
        json: Any = None,
        params: Optional[Dict[str, Any]] = None,
        content: Optional[_RawBody] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        return await self._request_with_retry(
            "PUT",
            path,
            json=json,
            params=params,
            content=content,
            headers=headers,
            timeout=timeout,
        )

    def stream(
        self,
        method: str,
        path: str,
        *,
        timeout: Optional[float] = None,
    ) -> Any:
        """Open a streaming HTTP response (async context manager).

        Usage: ``async with client.stream("GET", "/path") as resp:``
        then iterate ``resp.aiter_lines()`` or ``resp.aiter_bytes()``.
        No retry here — SSE connections are long-lived. Pass ``None``
        for indefinite streams (e.g. interactive PTYs).
        """
        return self._stream_client.stream(method, path, timeout=timeout)

    async def aclose(self) -> None:
        await self._stream_client.aclose()
        await self._client.aclose()

    async def close(self) -> None:
        await self._stream_client.aclose()
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Process-wide AsyncApiClient cache.
#
# Same rationale as get_shared_client in declaw.api.client: reuse the
# connection pool across class-method calls (Sandbox.create, Volumes.*)
# so only the first call per (loop, config) pays TCP + TLS.
#
# Keyed by the event loop identity as well as the config — an
# httpx.AsyncClient is tied to the loop that created it and is unusable
# from a different loop. Each fresh `asyncio.run` creates a new loop
# and therefore a fresh cache entry.
# ---------------------------------------------------------------------------

_AsyncSharedKey = Tuple[int, str, str, Optional[float]]
_async_shared_clients: Dict[_AsyncSharedKey, "AsyncApiClient"] = {}
_async_shared_clients_lock = asyncio.Lock()


def _async_shared_key(config: ConnectionConfig) -> _AsyncSharedKey:
    try:
        loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        # No running loop — fall back to a single key so callers who
        # `asyncio.run(get_shared_async_client(...))` once still hit the
        # cache. Normally this function is called from inside a running
        # coroutine so the running-loop branch fires.
        loop_id = 0
    return (loop_id, config.api_key or "", config.api_url or "", config.request_timeout)


async def get_shared_async_client(config: ConnectionConfig) -> AsyncApiClient:
    """Return a process-wide AsyncApiClient for the caller's event loop
    and config. Safe to call from many coroutines on the same loop.
    Do NOT `aclose()` the returned client; it is shared."""
    key = _async_shared_key(config)
    async with _async_shared_clients_lock:
        client = _async_shared_clients.get(key)
        if client is None:
            client = AsyncApiClient(config)
            _async_shared_clients[key] = client
        return client


async def reset_async_shared_clients() -> None:
    """Close every cached AsyncApiClient on the current loop. Safe to
    call from tests or long-running services that want to force a fresh
    connection pool."""
    async with _async_shared_clients_lock:
        for client in list(_async_shared_clients.values()):
            try:
                await client.aclose()
            except Exception:
                pass
        _async_shared_clients.clear()
