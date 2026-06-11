from __future__ import annotations

from typing import Callable, Iterator, Optional

from declaw.api.client import ApiClient
from declaw.exceptions import CommandExitException
from declaw.sandbox.commands.models import CommandResult


class CommandHandle:
    """Handle for interacting with a running background command."""

    def __init__(
        self,
        pid: int,
        sandbox_id: str,
        client: ApiClient,
    ):
        self._pid = pid
        self._sandbox_id = sandbox_id
        self._client = client
        self._result: Optional[CommandResult] = None

    @property
    def pid(self) -> int:
        return self._pid

    def wait(
        self,
        on_stdout: Optional[Callable[[str], None]] = None,
        on_stderr: Optional[Callable[[str], None]] = None,
    ) -> CommandResult:
        resp = self._client.get(f"/sandboxes/{self._sandbox_id}/commands/{self._pid}/wait")
        data = resp.json()
        result = CommandResult.from_dict(data)
        if on_stdout and result.stdout:
            for line in result.stdout.splitlines(keepends=True):
                on_stdout(line)
        if on_stderr and result.stderr:
            for line in result.stderr.splitlines(keepends=True):
                on_stderr(line)
        if result.exit_code != 0:
            raise CommandExitException(
                f"Command exited with code {result.exit_code}",
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                sandbox_id=self._sandbox_id,
            )
        self._result = result
        return result

    def kill(self) -> bool:
        resp = self._client.delete(f"/sandboxes/{self._sandbox_id}/commands/{self._pid}")
        return bool(resp.json().get("killed", False))

    def disconnect(self) -> None:
        pass

    def __iter__(self) -> Iterator[CommandResult]:
        if self._result:
            yield self._result
