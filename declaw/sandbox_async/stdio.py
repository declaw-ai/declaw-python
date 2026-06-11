from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Optional, Union

import httpx

from declaw.api.async_client import AsyncApiClient
from declaw.sandbox_sync.stdio import StdioResult, _as_bytes

DEFAULT_USER = "user"

OnDataCb = Union[
    Callable[[bytes], None],
    Callable[[bytes], Awaitable[None]],
]


class AsyncStdioProcess:
    """Async handle for an interactive subprocess with stdin pipe."""

    def __init__(
        self,
        cmd_id: str,
        sandbox_id: str,
        client: AsyncApiClient,
        on_stdout: Optional[OnDataCb] = None,
        on_stderr: Optional[OnDataCb] = None,
    ) -> None:
        self._cmd_id = cmd_id
        self._sandbox_id = sandbox_id
        self._client = client
        self._exit_code: Optional[int] = None
        self._stop = asyncio.Event()
        self._reader_task: Optional[asyncio.Task[None]] = None
        self._last_entry_id: int = 0

        if on_stdout is not None or on_stderr is not None:
            self._start_background_reader(on_stdout, on_stderr)

    @property
    def cmd_id(self) -> str:
        return self._cmd_id

    @property
    def exit_code(self) -> Optional[int]:
        return self._exit_code

    async def send_stdin(
        self,
        data: Union[bytes, str],
        request_timeout: Optional[float] = None,
    ) -> None:
        raw = _as_bytes(data)
        encoded = base64.b64encode(raw).decode("ascii")
        await self._client.post(
            f"/sandboxes/{self._sandbox_id}/stdio/{self._cmd_id}/stdin",
            json={"data": encoded},
            timeout=request_timeout,
        )

    async def close_stdin(self, request_timeout: Optional[float] = None) -> None:
        await self._client.post(
            f"/sandboxes/{self._sandbox_id}/stdio/{self._cmd_id}/stdin/close",
            timeout=request_timeout,
        )

    async def kill(self, request_timeout: Optional[float] = None) -> bool:
        self._stop.set()
        resp = await self._client.delete(
            f"/sandboxes/{self._sandbox_id}/stdio/{self._cmd_id}",
            timeout=request_timeout,
        )
        return bool(resp.json().get("killed", False))

    async def stream(
        self,
        on_stdout: Optional[OnDataCb] = None,
        on_stderr: Optional[OnDataCb] = None,
    ) -> StdioResult:
        if self._reader_task is not None:
            raise RuntimeError("background reader already running; use wait() instead")
        async for stream_type, chunk in self._iter_sse():
            if stream_type == "stdout" and on_stdout:
                result = on_stdout(chunk)
                if asyncio.iscoroutine(result):
                    await result
            elif stream_type == "stderr" and on_stderr:
                result = on_stderr(chunk)
                if asyncio.iscoroutine(result):
                    await result
        return StdioResult(exit_code=self._exit_code if self._exit_code is not None else -1)

    async def wait(self, timeout: Optional[float] = None) -> StdioResult:
        if self._reader_task is not None:
            done, _ = await asyncio.wait({self._reader_task}, timeout=timeout)
            if not done:
                raise TimeoutError("stdio wait timed out")
        else:
            async for _ in self._iter_sse():
                pass
        return StdioResult(exit_code=self._exit_code if self._exit_code is not None else -1)

    async def __aiter__(self) -> AsyncIterator[tuple[str, bytes]]:
        async for item in self._iter_sse():
            yield item

    async def _iter_sse(self) -> AsyncIterator[tuple[str, bytes]]:
        url = f"/sandboxes/{self._sandbox_id}/stdio/{self._cmd_id}/stream"
        if self._last_entry_id > 0:
            url += f"?last_entry_id={self._last_entry_id}"

        async with self._client.stream("GET", url, timeout=None) as resp:
            resp.raise_for_status()
            event: Optional[str] = None
            async for raw_line in resp.aiter_lines():
                if self._stop.is_set():
                    return
                if raw_line == "":
                    event = None
                    continue
                if raw_line.startswith("event:"):
                    event = raw_line[len("event:"):].strip()
                    continue
                if raw_line.startswith("data:"):
                    payload = raw_line[len("data:"):].strip()
                    if event == "exit":
                        try:
                            self._exit_code = int(json.loads(payload).get("exit_code", -1))
                        except Exception:
                            self._exit_code = -1
                        return
                    if event in ("stdout", "stderr"):
                        try:
                            blob = json.loads(payload)
                            entry_id = blob.get("entry_id", 0)
                            if entry_id > self._last_entry_id:
                                self._last_entry_id = entry_id
                            b64 = blob.get("data", "")
                            chunk = base64.b64decode(b64)
                        except Exception:
                            continue
                        yield (event, chunk)

    def _start_background_reader(
        self,
        on_stdout: Optional[OnDataCb],
        on_stderr: Optional[OnDataCb],
    ) -> None:
        async def _run() -> None:
            try:
                async for stream_type, chunk in self._iter_sse():
                    if self._stop.is_set():
                        break
                    try:
                        cb = on_stdout if stream_type == "stdout" else on_stderr
                        if cb:
                            result = cb(chunk)
                            if asyncio.iscoroutine(result):
                                await result
                    except Exception:
                        pass
            except (httpx.RemoteProtocolError, httpx.ReadError):
                pass

        self._reader_task = asyncio.create_task(_run())


class AsyncStdio:
    """Async module for interactive stdio subprocess sessions."""

    def __init__(self, sandbox_id: str, client: AsyncApiClient):
        self._sandbox_id = sandbox_id
        self._client = client

    async def start(
        self,
        cmd: str,
        envs: Optional[Dict[str, str]] = None,
        user: str = DEFAULT_USER,
        cwd: Optional[str] = None,
        on_stdout: Optional[OnDataCb] = None,
        on_stderr: Optional[OnDataCb] = None,
        request_timeout: Optional[float] = None,
    ) -> AsyncStdioProcess:
        body: Dict[str, Any] = {"cmd": cmd, "user": user}
        if envs:
            body["envs"] = envs
        if cwd:
            body["cwd"] = cwd

        resp = await self._client.post(
            f"/sandboxes/{self._sandbox_id}/stdio",
            json=body,
            timeout=request_timeout,
        )
        data = resp.json()
        return AsyncStdioProcess(
            cmd_id=data["cmd_id"],
            sandbox_id=self._sandbox_id,
            client=self._client,
            on_stdout=on_stdout,
            on_stderr=on_stderr,
        )
