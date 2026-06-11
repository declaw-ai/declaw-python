from __future__ import annotations

import os
import threading
import time
from typing import Any, AsyncIterable, BinaryIO, Dict, Iterable, Optional, Tuple, Union

import httpx


def _connection_limits() -> httpx.Limits:
    raw = os.environ.get("DECLAW_SDK_CONNECTIONS", "")
    try:
        n = int(raw)
        if n <= 0:
            n = 64
    except ValueError:
        n = 64
    return httpx.Limits(max_connections=n, max_keepalive_connections=n)

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

# Body types we forward to httpx on raw-bytes endpoints. httpx accepts
# bytes/str, a file-like, and sync/async iterables of bytes; we expose
# the same shape to SDK callers so streaming uploads work without
# forcing an in-memory materialization.
_RawBody = Union[bytes, str, Iterable[bytes], AsyncIterable[bytes], BinaryIO]

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


class ApiClient:
    """HTTP client for the Declaw API with auth, retry, and error mapping."""

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
        self._client = httpx.Client(
            base_url=self.config.api_url or "",
            timeout=self.config.request_timeout or 30.0,
            headers=self._base_headers(),
            http2=True,
            limits=_connection_limits(),
        )
        # Separate client for SSE streams. Long-lived SSE reads on a shared
        # HTTP/2 connection deadlock against concurrent request/response calls
        # because HTTP/2 flow control is per-connection: the SSE reader thread
        # blocks the socket, starving POST responses on the same connection.
        self._stream_client = httpx.Client(
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

    def _request_with_retry(
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
                response = self._client.request(
                    method,
                    path,
                    json=json,
                    params=params,
                    content=content,
                    headers=headers,
                    timeout=timeout,
                )
                if response.status_code >= 500 and attempt < self._max_retries - 1 and replayable:
                    time.sleep(self._retry_delay * (attempt + 1))
                    continue
                self._raise_for_status(response)
                return response
            except (httpx.ConnectError, httpx.ReadTimeout) as e:
                last_exc = e
                if attempt < self._max_retries - 1 and replayable:
                    time.sleep(self._retry_delay * (attempt + 1))
                    continue
                raise TimeoutException(f"Connection failed after {self._max_retries} retries: {e}")
        raise SandboxException(f"Request failed: {last_exc}")

    def get(
        self, path: str, *, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None
    ) -> httpx.Response:
        return self._request_with_retry("GET", path, params=params, timeout=timeout)

    def post(
        self,
        path: str,
        *,
        json: Any = None,
        params: Optional[Dict[str, Any]] = None,
        content: Optional[_RawBody] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        return self._request_with_retry(
            "POST",
            path,
            json=json,
            params=params,
            content=content,
            headers=headers,
            timeout=timeout,
        )

    def patch(
        self, path: str, *, json: Any = None, timeout: Optional[float] = None
    ) -> httpx.Response:
        return self._request_with_retry("PATCH", path, json=json, timeout=timeout)

    def delete(
        self,
        path: str,
        *,
        json: Any = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        return self._request_with_retry(
            "DELETE", path, json=json, params=params, timeout=timeout
        )

    def put(
        self,
        path: str,
        *,
        json: Any = None,
        params: Optional[Dict[str, Any]] = None,
        content: Optional[_RawBody] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        return self._request_with_retry(
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
        """Open a streaming HTTP response.

        Returns an httpx streaming context manager — callers should use it
        as ``with client.stream(...) as resp:`` and iterate ``resp.iter_lines()``
        or ``resp.iter_bytes()``. Unlike ``get/post``, no retry is applied
        because SSE connections are long-lived and retry semantics differ.
        """
        # Pass `None` timeout for indefinite streams (interactive PTYs). httpx
        # defaults would otherwise close an idle connection after 5s.
        return self._stream_client.stream(method, path, timeout=timeout)

    def close(self) -> None:
        self._stream_client.close()
        self._client.close()


# ---------------------------------------------------------------------------
# Process-wide ApiClient cache.
#
# Opening a fresh httpx.Client pays one TCP + TLS handshake (~60 ms against a
# cross-region endpoint). The SDK's hot class-method paths —
# Sandbox.create/connect/list, Volumes.*, Template.* — used to open a new
# client per call, so every call paid the handshake. `get_shared_client`
# returns a single ApiClient per (api_key, api_url, request_timeout), so
# callers reuse the same httpx connection pool and drop the handshake on
# every call after the first.
#
# The cache holds for the process lifetime. httpx.Client's own atexit hook
# releases sockets at interpreter shutdown; callers who want to force the
# release earlier can call `reset_shared_clients()`.
# ---------------------------------------------------------------------------

_SharedKey = Tuple[str, str, Optional[float]]
_shared_clients: Dict[_SharedKey, "ApiClient"] = {}
_shared_clients_lock = threading.Lock()


def _shared_key(config: ConnectionConfig) -> _SharedKey:
    return (config.api_key or "", config.api_url or "", config.request_timeout)


def get_shared_client(config: ConnectionConfig) -> ApiClient:
    """Return a process-wide ApiClient keyed by the given config.

    Safe to call concurrently from multiple threads — httpx.Client is
    thread-safe for issuing requests and the cache itself is mutex-guarded.
    Do NOT `close()` the returned client; it is shared.
    """
    key = _shared_key(config)
    with _shared_clients_lock:
        client = _shared_clients.get(key)
        if client is None:
            client = ApiClient(config)
            _shared_clients[key] = client
        return client


def reset_shared_clients() -> None:
    """Close and drop every cached ApiClient. Useful in tests and in
    long-running processes that want to force a new connection pool."""
    with _shared_clients_lock:
        for client in _shared_clients.values():
            try:
                client.close()
            except Exception:
                pass
        _shared_clients.clear()
