from __future__ import annotations

import base64
import json
import threading
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Any, Callable, Dict, Iterator, Optional, Union

import httpx

from declaw.api.client import ApiClient
from declaw.sandbox.commands.models import PtySize

DEFAULT_USER = "user"


@dataclass
class PtyResult:
    """Outcome of a PTY session.

    ``exit_code`` is the remote shell's exit status. Int-coercible so
    ``int(result)`` and ``result == 0`` continue to work for callers that
    treat it as a plain integer.
    """

    exit_code: int

    def __int__(self) -> int:
        return self.exit_code

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PtyResult):
            return self.exit_code == other.exit_code
        if isinstance(other, int):
            return self.exit_code == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.exit_code)


def _as_bytes(data: Union[bytes, str]) -> bytes:
    if isinstance(data, str):
        return data.encode("utf-8")
    return data


class PtyHandle:
    """Handle to a running PTY session.

    Exposes the live output stream in two idiomatic shapes:

    - **Iterator**: ``for chunk in handle: ...`` — blocks until the next
      chunk of PTY output is available; returns ``bytes``. Stops when the
      remote process exits.
    - **Callback**: pass ``on_data=`` into ``Pty.create(...)`` to run a
      callable on every chunk. This starts a background reader thread so
      the caller can still send input from the main thread.

    Both shapes share the same underlying stream. Use one or the other —
    the first call to ``__iter__`` or the background reader (started by
    ``on_data``) consumes the stream.
    """

    def __init__(
        self,
        pid: int,
        sandbox_id: str,
        client: ApiClient,
        on_data: Optional[Callable[[bytes], None]] = None,
    ) -> None:
        self._pid = pid
        self._sandbox_id = sandbox_id
        self._client = client
        self._exit_code: Optional[int] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._reader_queue: Optional[Queue[Optional[bytes]]] = None
        self._stop_event = threading.Event()
        if on_data is not None:
            self._start_background_reader(on_data)

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def exit_code(self) -> Optional[int]:
        """Remote process exit code, or ``None`` if the PTY is still running."""
        return self._exit_code

    def __iter__(self) -> Iterator[bytes]:
        if self._reader_thread is not None:
            assert self._reader_queue is not None
            while True:
                try:
                    chunk = self._reader_queue.get(timeout=0.1)
                except Empty:
                    if not self._reader_thread.is_alive():
                        return
                    continue
                if chunk is None:
                    return
                yield chunk
            return
        yield from self._iter_sse()

    def _iter_sse(self) -> Iterator[bytes]:
        with self._client.stream(
            "GET",
            f"/sandboxes/{self._sandbox_id}/pty/{self._pid}/stream",
            timeout=None,
        ) as resp:
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

    def _start_background_reader(self, on_data: Callable[[bytes], None]) -> None:
        self._reader_queue = Queue(maxsize=0)

        def _run() -> None:
            try:
                for chunk in self._iter_sse():
                    if self._stop_event.is_set():
                        break
                    try:
                        on_data(chunk)
                    except Exception:
                        pass
                    if self._reader_queue is not None:
                        self._reader_queue.put(chunk)
            except (httpx.RemoteProtocolError, httpx.ReadError):
                pass
            finally:
                if self._reader_queue is not None:
                    self._reader_queue.put(None)  # sentinel

        t = threading.Thread(target=_run, daemon=True, name=f"pty-reader-{self._pid}")
        self._reader_thread = t
        t.start()

    def send_stdin(
        self,
        data: Union[bytes, str],
        request_timeout: Optional[float] = None,
    ) -> None:
        raw = _as_bytes(data)
        self._client.post(
            f"/sandboxes/{self._sandbox_id}/pty/{self._pid}/stdin",
            json={"data": raw.decode("utf-8", errors="replace")},
            timeout=request_timeout,
        )

    def resize(self, size: PtySize, request_timeout: Optional[float] = None) -> None:
        self._client.patch(
            f"/sandboxes/{self._sandbox_id}/pty/{self._pid}",
            json={"size": size.to_dict()},
            timeout=request_timeout,
        )

    def disconnect(self) -> None:
        """Stop consuming the output stream without killing the PTY.

        The remote process keeps running; a subsequent ``Pty.connect(pid)``
        call can reattach a new callback to the same session. This is the
        right choice when you want to hand off a running PTY to another
        process or pause/resume the UI without losing state.
        """
        self._stop_event.set()

    def kill(self, request_timeout: Optional[float] = None) -> bool:
        self._stop_event.set()
        resp = self._client.delete(
            f"/sandboxes/{self._sandbox_id}/pty/{self._pid}",
            timeout=request_timeout,
        )
        return bool(resp.json().get("killed", False))

    def wait(self, timeout: Optional[float] = None) -> PtyResult:
        """Block until the PTY exits and return a :class:`PtyResult`.

        If a background reader is running, waits for it to finish; otherwise
        drains the stream inline (discarding output). The returned object
        is int-coercible, so ``int(handle.wait())`` and
        ``handle.wait() == 0`` both work.
        """
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=timeout)
        else:
            try:
                for _ in self._iter_sse():
                    pass
            except (httpx.RemoteProtocolError, httpx.ReadError):
                pass
        return PtyResult(exit_code=self._exit_code if self._exit_code is not None else -1)


class Pty:
    """Module for interacting with PTYs (pseudo-terminals) in the sandbox."""

    def __init__(self, sandbox_id: str, client: ApiClient):
        self._sandbox_id = sandbox_id
        self._client = client

    def create(
        self,
        size: PtySize = PtySize(),
        user: str = DEFAULT_USER,
        cwd: Optional[str] = None,
        envs: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = 3600,
        on_data: Optional[Callable[[bytes], None]] = None,
        request_timeout: Optional[float] = None,
    ) -> PtyHandle:
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

        resp = self._client.post(
            f"/sandboxes/{self._sandbox_id}/pty",
            json=body,
            timeout=request_timeout,
        )
        data = resp.json()
        return PtyHandle(
            pid=data["pid"],
            sandbox_id=self._sandbox_id,
            client=self._client,
            on_data=on_data,
        )

    def connect(
        self,
        pid: int,
        on_data: Optional[Callable[[bytes], None]] = None,
    ) -> PtyHandle:
        """Reattach to an already-running PTY by its pid.

        The caller gets a fresh :class:`PtyHandle` that streams the live
        output of the existing session. Multiple clients can subscribe to
        the same pid concurrently — each receives output from the moment
        it connects (no scrollback replay).
        """
        return PtyHandle(
            pid=pid,
            sandbox_id=self._sandbox_id,
            client=self._client,
            on_data=on_data,
        )

    # --- Low-level API by pid (kept for callers that already hold one). ---

    def kill(self, pid: int, request_timeout: Optional[float] = None) -> bool:
        resp = self._client.delete(
            f"/sandboxes/{self._sandbox_id}/pty/{pid}",
            timeout=request_timeout,
        )
        return bool(resp.json().get("killed", False))

    def send_stdin(
        self,
        pid: int,
        data: Union[bytes, str],
        request_timeout: Optional[float] = None,
    ) -> None:
        raw = _as_bytes(data)
        self._client.post(
            f"/sandboxes/{self._sandbox_id}/pty/{pid}/stdin",
            json={"data": raw.decode("utf-8", errors="replace")},
            timeout=request_timeout,
        )

    def resize(self, pid: int, size: PtySize, request_timeout: Optional[float] = None) -> None:
        self._client.patch(
            f"/sandboxes/{self._sandbox_id}/pty/{pid}",
            json={"size": size.to_dict()},
            timeout=request_timeout,
        )
