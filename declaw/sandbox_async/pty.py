from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Optional, Union

import httpx

from declaw.api.async_client import AsyncApiClient
from declaw.sandbox.commands.models import PtySize
from declaw.sandbox_sync.pty import PtyResult, _as_bytes

DEFAULT_USER = "user"


OnDataCb = Union[
    Callable[[bytes], None],
    Callable[[bytes], Awaitable[None]],
]


class AsyncPtyHandle:
    """Handle to a running PTY session driven from async code.

    Shape mirrors the sync :class:`declaw.sandbox_sync.pty.PtyHandle`:
    pass ``on_data=`` to receive output via callback (coroutine-or-sync),
    or ``async for chunk in handle:`` to iterate bytes directly.
    """

    def __init__(
        self,
        pid: int,
        sandbox_id: str,
        client: AsyncApiClient,
        on_data: Optional[OnDataCb] = None,
    ) -> None:
        self._pid = pid
        self._sandbox_id = sandbox_id
        self._client = client
        self._exit_code: Optional[int] = None
        self._stop = asyncio.Event()
        self._reader_task: Optional[asyncio.Task[None]] = None
        self._queue: Optional[asyncio.Queue[Optional[bytes]]] = None
        if on_data is not None:
            self._start_background_reader(on_data)

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def exit_code(self) -> Optional[int]:
        return self._exit_code

    async def _iter_sse(self) -> AsyncIterator[bytes]:
        async with self._client.stream(
            "GET",
            f"/sandboxes/{self._sandbox_id}/pty/{self._pid}/stream",
            timeout=None,
        ) as resp:
            resp.raise_for_status()
            event: Optional[str] = None
            async for raw_line in resp.aiter_lines():
                if self._stop.is_set():
                    return
                if raw_line == "":
                    event = None
                    continue
                if raw_line.startswith("event:"):
                    event = raw_line[len("event:") :].strip()
                    continue
                if raw_line.startswith("data:"):
                    payload = raw_line[len("data:") :].strip()
                    if event == "exit":
                        try:
                            self._exit_code = int(json.loads(payload).get("exit_code", -1))
                        except Exception:
                            self._exit_code = -1
                        return
                    if event == "data" or event is None:
                        try:
                            blob = json.loads(payload)
                            b64 = blob.get("data", "")
                        except Exception:
                            continue
                        try:
                            yield base64.b64decode(b64)
                        except Exception:
                            continue

    def __aiter__(self) -> AsyncIterator[bytes]:
        if self._reader_task is not None:
            return self._drain_queue()
        return self._iter_sse()

    async def _drain_queue(self) -> AsyncIterator[bytes]:
        assert self._queue is not None
        while True:
            chunk = await self._queue.get()
            if chunk is None:
                return
            yield chunk

    def _start_background_reader(self, on_data: OnDataCb) -> None:
        self._queue = asyncio.Queue()

        async def _run() -> None:
            try:
                async for chunk in self._iter_sse():
                    if self._stop.is_set():
                        break
                    try:
                        r = on_data(chunk)
                        if asyncio.iscoroutine(r):
                            await r
                    except Exception:
                        pass
                    assert self._queue is not None
                    await self._queue.put(chunk)
            except (httpx.RemoteProtocolError, httpx.ReadError):
                pass
            finally:
                assert self._queue is not None
                await self._queue.put(None)

        self._reader_task = asyncio.ensure_future(_run())

    async def send_stdin(
        self,
        data: Union[bytes, str],
        request_timeout: Optional[float] = None,
    ) -> None:
        raw = _as_bytes(data)
        await self._client.post(
            f"/sandboxes/{self._sandbox_id}/pty/{self._pid}/stdin",
            json={"data": raw.decode("utf-8", errors="replace")},
            timeout=request_timeout,
        )

    async def resize(self, size: PtySize, request_timeout: Optional[float] = None) -> None:
        await self._client.patch(
            f"/sandboxes/{self._sandbox_id}/pty/{self._pid}",
            json={"size": size.to_dict()},
            timeout=request_timeout,
        )

    async def disconnect(self) -> None:
        """Stop consuming output without killing the remote PTY."""
        self._stop.set()
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except Exception:
                pass

    async def kill(self, request_timeout: Optional[float] = None) -> bool:
        self._stop.set()
        resp = await self._client.delete(
            f"/sandboxes/{self._sandbox_id}/pty/{self._pid}",
            timeout=request_timeout,
        )
        return bool(resp.json().get("killed", False))

    async def wait(self, timeout: Optional[float] = None) -> PtyResult:
        """Await shell exit. Returns :class:`PtyResult`."""
        if self._reader_task is not None:
            try:
                await asyncio.wait_for(self._reader_task, timeout=timeout)
            except asyncio.TimeoutError:
                pass
        else:
            try:
                async for _ in self._iter_sse():
                    pass
            except (httpx.RemoteProtocolError, httpx.ReadError):
                pass
        return PtyResult(exit_code=self._exit_code if self._exit_code is not None else -1)


class AsyncPty:
    """Async equivalent of :class:`declaw.sandbox_sync.pty.Pty`.

    Same REST endpoints, same envd semantics; ``httpx.AsyncClient`` instead
    of a thread pool. Exposed on :class:`AsyncSandbox` as ``sandbox.pty``.
    """

    def __init__(self, sandbox_id: str, client: AsyncApiClient):
        self._sandbox_id = sandbox_id
        self._client = client

    async def create(
        self,
        size: PtySize = PtySize(),
        user: str = DEFAULT_USER,
        cwd: Optional[str] = None,
        envs: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = 3600,
        on_data: Optional[OnDataCb] = None,
        request_timeout: Optional[float] = None,
    ) -> AsyncPtyHandle:
        body: Dict[str, Any] = {
            "size": size.to_dict(),
            "user": user,
        }
        if cwd:
            body["cwd"] = cwd
        if envs:
            body["envs"] = envs
        if timeout is not None:
            body["timeout"] = timeout

        resp = await self._client.post(
            f"/sandboxes/{self._sandbox_id}/pty",
            json=body,
            timeout=request_timeout,
        )
        data = resp.json()
        return AsyncPtyHandle(
            pid=data["pid"],
            sandbox_id=self._sandbox_id,
            client=self._client,
            on_data=on_data,
        )

    def connect(
        self,
        pid: int,
        on_data: Optional[OnDataCb] = None,
    ) -> AsyncPtyHandle:
        """Reattach to a running PTY by pid; returns a fresh handle."""
        return AsyncPtyHandle(
            pid=pid,
            sandbox_id=self._sandbox_id,
            client=self._client,
            on_data=on_data,
        )

    # --- Low-level API by pid ---

    async def kill(self, pid: int, request_timeout: Optional[float] = None) -> bool:
        resp = await self._client.delete(
            f"/sandboxes/{self._sandbox_id}/pty/{pid}",
            timeout=request_timeout,
        )
        return bool(resp.json().get("killed", False))

    async def send_stdin(
        self,
        pid: int,
        data: Union[bytes, str],
        request_timeout: Optional[float] = None,
    ) -> None:
        raw = _as_bytes(data)
        await self._client.post(
            f"/sandboxes/{self._sandbox_id}/pty/{pid}/stdin",
            json={"data": raw.decode("utf-8", errors="replace")},
            timeout=request_timeout,
        )

    async def resize(
        self,
        pid: int,
        size: PtySize,
        request_timeout: Optional[float] = None,
    ) -> None:
        await self._client.patch(
            f"/sandboxes/{self._sandbox_id}/pty/{pid}",
            json={"size": size.to_dict()},
            timeout=request_timeout,
        )
