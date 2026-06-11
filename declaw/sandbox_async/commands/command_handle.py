from __future__ import annotations

from typing import Callable, Optional

from declaw.api.async_client import AsyncApiClient
from declaw.exceptions import CommandExitException
from declaw.sandbox.commands.models import CommandResult


class AsyncCommandHandle:
    """Async handle for interacting with a running background command."""

    def __init__(self, pid: int, sandbox_id: str, client: AsyncApiClient):
        self._pid = pid
        self._sandbox_id = sandbox_id
        self._client = client

    @property
    def pid(self) -> int:
        return self._pid

    async def wait(
        self,
        on_stdout: Optional[Callable[[str], None]] = None,
        on_stderr: Optional[Callable[[str], None]] = None,
    ) -> CommandResult:
        resp = await self._client.get(f"/sandboxes/{self._sandbox_id}/commands/{self._pid}/wait")
        result = CommandResult.from_dict(resp.json())
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
        return result

    async def kill(self) -> bool:
        resp = await self._client.delete(f"/sandboxes/{self._sandbox_id}/commands/{self._pid}")
        return bool(resp.json().get("killed", False))

    async def disconnect(self) -> None:
        pass
