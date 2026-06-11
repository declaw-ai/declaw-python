from __future__ import annotations

import base64
import json
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, Optional, Union

import httpx

from declaw.api.client import ApiClient

DEFAULT_USER = "user"


@dataclass
class StdioResult:
    exit_code: int

    def __int__(self) -> int:
        return self.exit_code

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (StdioResult, int)):
            return self.exit_code == (other if isinstance(other, int) else other.exit_code)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.exit_code)


def _as_bytes(data: Union[bytes, str]) -> bytes:
    if isinstance(data, str):
        return data.encode("utf-8")
    return data


class StdioProcess:
    """Handle for an interactive subprocess with stdin pipe.

    Provides bidirectional I/O: send data to the process via
    :meth:`send_stdin`, receive stdout/stderr via :meth:`stream`
    or iteration, and close the input pipe via :meth:`close_stdin`.
    """

    def __init__(
        self,
        cmd_id: str,
        sandbox_id: str,
        client: ApiClient,
        on_stdout: Optional[Callable[[bytes], None]] = None,
        on_stderr: Optional[Callable[[bytes], None]] = None,
    ) -> None:
        self._cmd_id = cmd_id
        self._sandbox_id = sandbox_id
        self._client = client
        self._exit_code: Optional[int] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_entry_id: int = 0

        if on_stdout is not None or on_stderr is not None:
            self._start_background_reader(on_stdout, on_stderr)

    @property
    def cmd_id(self) -> str:
        return self._cmd_id

    @property
    def exit_code(self) -> Optional[int]:
        return self._exit_code

    def send_stdin(
        self,
        data: Union[bytes, str],
        request_timeout: Optional[float] = None,
    ) -> None:
        raw = _as_bytes(data)
        encoded = base64.b64encode(raw).decode("ascii")
        self._client.post(
            f"/sandboxes/{self._sandbox_id}/stdio/{self._cmd_id}/stdin",
            json={"data": encoded},
            timeout=request_timeout,
        )

    def close_stdin(self, request_timeout: Optional[float] = None) -> None:
        self._client.post(
            f"/sandboxes/{self._sandbox_id}/stdio/{self._cmd_id}/stdin/close",
            timeout=request_timeout,
        )

    def kill(self, request_timeout: Optional[float] = None) -> bool:
        self._stop_event.set()
        resp = self._client.delete(
            f"/sandboxes/{self._sandbox_id}/stdio/{self._cmd_id}",
            timeout=request_timeout,
        )
        return bool(resp.json().get("killed", False))

    def stream(
        self,
        on_stdout: Optional[Callable[[bytes], None]] = None,
        on_stderr: Optional[Callable[[bytes], None]] = None,
    ) -> StdioResult:
        """Block until the process exits, calling back with output chunks."""
        if self._reader_thread is not None:
            raise RuntimeError("background reader already running; use wait() instead")
        for stream_type, chunk in self._iter_sse():
            if on_stdout and stream_type == "stdout":
                on_stdout(chunk)
            if on_stderr and stream_type == "stderr":
                on_stderr(chunk)
        return StdioResult(exit_code=self._exit_code if self._exit_code is not None else -1)

    def wait(self, timeout: Optional[float] = None) -> StdioResult:
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=timeout)
        else:
            for _ in self._iter_sse():
                pass
        return StdioResult(exit_code=self._exit_code if self._exit_code is not None else -1)

    def __iter__(self) -> Iterator[tuple[str, bytes]]:
        if self._reader_thread is not None:
            raise RuntimeError("background reader already running; use wait() instead")
        yield from self._iter_sse()

    def _iter_sse(self) -> Iterator[tuple[str, bytes]]:
        url = f"/sandboxes/{self._sandbox_id}/stdio/{self._cmd_id}/stream"
        if self._last_entry_id > 0:
            url += f"?last_entry_id={self._last_entry_id}"

        with self._client.stream("GET", url, timeout=None) as resp:
            resp.raise_for_status()
            event: Optional[str] = None
            for raw_line in resp.iter_lines():
                if self._stop_event.is_set():
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
        on_stdout: Optional[Callable[[bytes], None]],
        on_stderr: Optional[Callable[[bytes], None]],
    ) -> None:
        def _run() -> None:
            try:
                for stream_type, chunk in self._iter_sse():
                    if self._stop_event.is_set():
                        break
                    try:
                        if stream_type == "stdout" and on_stdout:
                            on_stdout(chunk)
                        elif stream_type == "stderr" and on_stderr:
                            on_stderr(chunk)
                    except Exception:
                        pass
            except (httpx.RemoteProtocolError, httpx.ReadError):
                pass

        t = threading.Thread(target=_run, daemon=True, name=f"stdio-reader-{self._cmd_id[:8]}")
        self._reader_thread = t
        t.start()


class Stdio:
    """Module for interactive stdio subprocess sessions in the sandbox."""

    def __init__(self, sandbox_id: str, client: ApiClient):
        self._sandbox_id = sandbox_id
        self._client = client

    def start(
        self,
        cmd: str,
        envs: Optional[Dict[str, str]] = None,
        user: str = DEFAULT_USER,
        cwd: Optional[str] = None,
        on_stdout: Optional[Callable[[bytes], None]] = None,
        on_stderr: Optional[Callable[[bytes], None]] = None,
        request_timeout: Optional[float] = None,
    ) -> StdioProcess:
        """Start a process with an open stdin pipe for interactive I/O."""
        body: Dict[str, Any] = {"cmd": cmd, "user": user}
        if envs:
            body["envs"] = envs
        if cwd:
            body["cwd"] = cwd

        resp = self._client.post(
            f"/sandboxes/{self._sandbox_id}/stdio",
            json=body,
            timeout=request_timeout,
        )
        data = resp.json()
        return StdioProcess(
            cmd_id=data["cmd_id"],
            sandbox_id=self._sandbox_id,
            client=self._client,
            on_stdout=on_stdout,
            on_stderr=on_stderr,
        )
