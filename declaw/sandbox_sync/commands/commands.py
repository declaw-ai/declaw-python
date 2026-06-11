from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Literal, Optional, Union, overload

import httpx

from declaw.api.client import ApiClient
from declaw.sandbox.commands.models import CommandResult, ProcessInfo
from declaw.sandbox_sync.commands.command_handle import CommandHandle

DEFAULT_USER = "user"


class Commands:
    """Module for executing commands in the sandbox."""

    def __init__(self, sandbox_id: str, client: ApiClient):
        self._sandbox_id = sandbox_id
        self._client = client

    @overload
    def run(
        self,
        cmd: str,
        background: Literal[False] = ...,
        envs: Optional[Dict[str, str]] = ...,
        user: str = ...,
        cwd: Optional[str] = ...,
        on_stdout: Optional[Callable[[str], None]] = ...,
        on_stderr: Optional[Callable[[str], None]] = ...,
        stdin: Optional[bool] = ...,
        timeout: Optional[float] = ...,
        request_timeout: Optional[float] = ...,
    ) -> CommandResult: ...

    @overload
    def run(
        self,
        cmd: str,
        background: Literal[True],
        envs: Optional[Dict[str, str]] = ...,
        user: str = ...,
        cwd: Optional[str] = ...,
        on_stdout: None = ...,
        on_stderr: None = ...,
        stdin: Optional[bool] = ...,
        timeout: Optional[float] = ...,
        request_timeout: Optional[float] = ...,
    ) -> CommandHandle: ...

    def run(
        self,
        cmd: str,
        background: bool = False,
        envs: Optional[Dict[str, str]] = None,
        user: str = DEFAULT_USER,
        cwd: Optional[str] = None,
        on_stdout: Optional[Callable[[str], None]] = None,
        on_stderr: Optional[Callable[[str], None]] = None,
        stdin: Optional[bool] = None,
        timeout: Optional[float] = 60,
        request_timeout: Optional[float] = None,
    ) -> Union[CommandResult, CommandHandle]:
        body: Dict[str, Any] = {
            "cmd": cmd,
            "background": background,
            "user": user,
        }
        if envs:
            body["envs"] = envs
        if cwd:
            body["cwd"] = cwd
        if stdin is not None:
            body["stdin"] = stdin
        if timeout is not None:
            body["timeout"] = timeout

        resp = self._client.post(
            f"/sandboxes/{self._sandbox_id}/commands",
            json=body,
            timeout=request_timeout,
        )
        data = resp.json()

        if background:
            return CommandHandle(
                pid=data["pid"],
                sandbox_id=self._sandbox_id,
                client=self._client,
            )

        result = CommandResult.from_dict(data)
        if on_stdout and result.stdout:
            for line in result.stdout.splitlines(keepends=True):
                on_stdout(line)
        if on_stderr and result.stderr:
            for line in result.stderr.splitlines(keepends=True):
                on_stderr(line)
        return result

    def list(self, request_timeout: Optional[float] = None) -> List[ProcessInfo]:
        resp = self._client.get(
            f"/sandboxes/{self._sandbox_id}/commands",
            timeout=request_timeout,
        )
        return [ProcessInfo.from_dict(p) for p in (resp.json() or [])]

    def kill(self, pid: int, request_timeout: Optional[float] = None) -> bool:
        resp = self._client.delete(
            f"/sandboxes/{self._sandbox_id}/commands/{pid}",
            timeout=request_timeout,
        )
        return bool(resp.json().get("killed", False))

    def send_stdin(self, pid: int, data: str, request_timeout: Optional[float] = None) -> None:
        self._client.post(
            f"/sandboxes/{self._sandbox_id}/commands/{pid}/stdin",
            json={"data": data},
            timeout=request_timeout,
        )

    def connect(
        self, pid: int, timeout: Optional[float] = 60, request_timeout: Optional[float] = None
    ) -> CommandHandle:
        return CommandHandle(
            pid=pid,
            sandbox_id=self._sandbox_id,
            client=self._client,
        )

    def run_stream(
        self,
        cmd: str,
        on_stdout: Optional[Callable[[str], None]] = None,
        on_stderr: Optional[Callable[[str], None]] = None,
        envs: Optional[Dict[str, str]] = None,
        user: str = DEFAULT_USER,
        cwd: Optional[str] = None,
        timeout: Optional[float] = 60,
    ) -> CommandResult:
        """
        Run a command with real-time streaming of stdout/stderr.

        Callbacks are invoked as each line of output is received,
        not after the command completes.

        Args:
            cmd: Command to execute
            on_stdout: Callback for each stdout line (called in real-time)
            on_stderr: Callback for each stderr line (called in real-time)
            envs: Environment variables
            user: User to run as
            cwd: Working directory
            timeout: Command timeout in seconds

        Returns:
            CommandResult with full stdout/stderr after completion
        """
        body: Dict[str, Any] = {
            "cmd": cmd,
            "stream": True,
            "user": user,
        }
        if envs:
            body["envs"] = envs
        if cwd:
            body["cwd"] = cwd
        if timeout is not None:
            body["timeout"] = timeout

        # Get envd URL from the sandbox
        envd_url = f"{self._client.config.api_url}/sandboxes/{self._sandbox_id}/commands/stream"

        stdout_lines: List[str] = []
        stderr_lines: List[str] = []
        exit_code = 0

        with httpx.stream(
            "POST",
            envd_url,
            json=body,
            headers={"X-API-Key": self._client.config.api_key},
            timeout=timeout or 60,
        ) as response:
            for line in response.iter_lines():
                if not line:
                    continue

                # Parse SSE format
                if line.startswith("event:"):
                    continue
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    try:
                        data = json.loads(data_str)

                        if data.get("type") == "stdout":
                            content = data.get("data", "")
                            stdout_lines.append(content)
                            if on_stdout:
                                on_stdout(content)
                        elif data.get("type") == "stderr":
                            content = data.get("data", "")
                            stderr_lines.append(content)
                            if on_stderr:
                                on_stderr(content)
                        elif "exit_code" in data:
                            exit_code = data["exit_code"]
                        elif "error" in data:
                            stderr_lines.append(data["error"])
                            if on_stderr:
                                on_stderr(data["error"])
                    except json.JSONDecodeError:
                        pass

        return CommandResult(
            stdout="\n".join(stdout_lines),
            stderr="\n".join(stderr_lines),
            exit_code=exit_code,
        )
