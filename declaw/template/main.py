from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import httpx

from declaw.exceptions import (
    AuthenticationError,
    BuildError,
    ConflictError,
    InsufficientBalanceException,
    InvalidArgumentError,
    NotEnoughSpaceError,
    NotFoundError,
    SandboxError,
    TimeoutError,
)

#: Build states reported by the API. A build starts ``building`` and ends
#: ``completed`` or ``failed``.
BUILD_STATUS_BUILDING = "building"
BUILD_STATUS_COMPLETED = "completed"
BUILD_STATUS_FAILED = "failed"

#: Seconds between status checks while ``Template.build`` waits.
BUILD_POLL_INTERVAL = 3.0

#: Default for how long ``Template.build`` waits, in seconds. The server fails
#: a build after 30 minutes, and marks a stranded one failed well within an
#: hour, so this only bounds the wait for a build that is still progressing.
DEFAULT_BUILD_TIMEOUT = 3600.0

#: Seconds status checks may keep failing temporarily (5xx, 408, 429, or no
#: response) before ``Template.build`` stops waiting. It rides out a
#: sandbox-manager restart; the build itself keeps running.
BUILD_POLL_ERROR_WINDOW = 120.0

#: How much build output a ``BuildError`` message quotes.
_FAILURE_LOG_LINES = 20

#: The line sandbox-manager puts first once it starts dropping a build's oldest
#: output (store.BuildLogTruncationNotice). It must match exactly: it is how
#: _LogCursor tells a trimmed log from a growing one.
BUILD_LOG_TRUNCATION_NOTICE = "... [earlier build output truncated]"

#: How many of the newest delivered lines _LogCursor looks for in a trimmed log.
_LOG_ANCHOR_LINES = 64

#: Failed status checks that waiting cannot change: the API rejected the request.
_REJECTIONS = (
    AuthenticationError,
    ConflictError,
    InsufficientBalanceException,
    InvalidArgumentError,
    NotEnoughSpaceError,
    NotFoundError,
)


@dataclass
class CopyItem:
    src: str
    dst: str
    mode: Optional[int] = None


@dataclass
class TemplateBase:
    """Builder for defining sandbox templates via a fluent API."""

    _base_image: str = "ubuntu:22.04"
    _run_cmds: List[List[str]] = field(default_factory=list)
    _copies: List[CopyItem] = field(default_factory=list)
    _envs: Dict[str, str] = field(default_factory=dict)
    _apt_packages: List[str] = field(default_factory=list)
    _start_cmd: Optional[str] = None
    _start_cmd_ready: Optional[Any] = None
    # When set, the server uses this Dockerfile verbatim and ignores the
    # helper fields above. Use for multi-stage builds, ARG, ONBUILD, etc.
    _dockerfile: Optional[str] = None

    def from_base_image(self, image: str = "ubuntu:22.04") -> TemplateBase:
        self._base_image = image
        return self

    def from_dockerfile(self, content: str) -> TemplateBase:
        """Use a raw Dockerfile string instead of the structured helpers.

        When set, all other ``apt_install`` / ``run_cmd`` / ``set_envs`` /
        ``copy`` / ``set_start_cmd`` / ``from_base_image`` calls on this
        spec are ignored — the Dockerfile is sent to the build worker
        verbatim.

        Args:
            content: The full Dockerfile contents. Must contain a
                ``FROM`` instruction. Capped server-side at 64 KiB.
        """
        self._dockerfile = content
        return self

    def run_cmd(self, cmds: List[str]) -> TemplateBase:
        self._run_cmds.append(cmds)
        return self

    def copy(self, src: str, dst: str, mode: Optional[int] = None) -> TemplateBase:
        """Copy a local file into the template.

        Not supported yet: a template build cannot upload local files, so
        building a template that uses ``copy()`` raises
        ``InvalidArgumentError``. Fetch the file in a ``run_cmd`` step, or use
        ``from_dockerfile``.
        """
        self._copies.append(CopyItem(src=src, dst=dst, mode=mode))
        return self

    def set_envs(self, envs: Dict[str, str]) -> TemplateBase:
        self._envs.update(envs)
        return self

    def apt_install(self, *packages: str) -> TemplateBase:
        self._apt_packages.extend(packages)
        return self

    def set_start_cmd(self, cmd: str, ready_check: Optional[Any] = None) -> TemplateBase:
        self._start_cmd = cmd
        self._start_cmd_ready = ready_check
        return self

    def to_dict(self) -> Dict[str, Any]:
        # Raw Dockerfile path: send only the dockerfile field; the server
        # ignores helpers when this is set.
        if self._dockerfile is not None:
            return {"dockerfile": self._dockerfile}
        # Field names are the server's (models.TemplateSpec). It ignores any
        # name it does not know, so a misnamed field is silently dropped —
        # which is how apt_install() once did nothing. Copies are not
        # serialized: builds reject them before sending (see build_request_body).
        result: Dict[str, Any] = {"base_image": self._base_image}
        if self._run_cmds:
            # Server expects each run_cmd as a single shell line. The
            # helper accepts both styles — ``run_cmd(["pip3 install x"])``
            # and ``run_cmd(["pip3", "install", "x"])`` — and we
            # space-join the inner list so both serialize the same. (#233)
            result["run_cmds"] = [" ".join(group) for group in self._run_cmds]
        if self._envs:
            result["envs"] = self._envs
        if self._apt_packages:
            result["packages"] = self._apt_packages
        if self._start_cmd:
            result["start_cmd"] = self._start_cmd
        return result


def build_request_body(
    template: TemplateBase,
    alias: str,
    cpu_count: Optional[int] = None,
    memory_mb: Optional[int] = None,
    disk_mb: Optional[int] = None,
) -> Dict[str, Any]:
    """Body for ``POST /templates/build``: the spec nested under
    ``template``, with the alias and resources beside it."""
    if template._copies:
        raise InvalidArgumentError(
            "TemplateBase.copy() is not supported yet: a template build cannot upload "
            "local files. Fetch them in a run_cmd step, or use from_dockerfile()."
        )
    body: Dict[str, Any] = {
        "template": template.to_dict(),
        "alias": alias,
    }
    if cpu_count is not None:
        body["cpu_count"] = cpu_count
    if memory_mb is not None:
        body["memory_mb"] = memory_mb
    if disk_mb is not None:
        body["disk_mb"] = disk_mb
    return body


def build_failed_error(status: TemplateBuildStatus) -> BuildError:
    """The error for a failed build, quoting the end of its logs."""
    message = f"template build {status.build_id} failed"
    tail = status.logs[-_FAILURE_LOG_LINES:]
    if tail:
        message += ":\n" + "\n".join(tail)
    return BuildError(message, build_id=status.build_id, logs=status.logs)


@dataclass
class BuildInfo:
    build_id: str
    status: str
    template_id: Optional[str] = None
    #: Build output. Empty in the response to starting a build; filled when
    #: ``Template.build`` returns a finished build.
    logs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "build_id": self.build_id,
            "status": self.status,
            "template_id": self.template_id,
            "logs": self.logs,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BuildInfo:
        return cls(
            build_id=data["build_id"],
            status=data["status"],
            template_id=data.get("template_id"),
            logs=data.get("logs") or [],
        )


@dataclass
class TemplateBuildStatus:
    build_id: str
    status: str
    logs: List[str] = field(default_factory=list)
    template_id: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TemplateBuildStatus:
        return cls(
            build_id=data["build_id"],
            status=data["status"],
            # A build with no output yet serializes its logs as null.
            logs=data.get("logs") or [],
            template_id=data.get("template_id"),
        )


class _LogCursor:
    """Hands out each line of a build's log once across repeated polls.

    The server keeps a bounded number of lines. Until it hits the bound the log
    only grows, and the new lines are those past the last length seen. After,
    it drops the oldest lines and puts BUILD_LOG_TRUNCATION_NOTICE first, so the
    length stops changing and positions shift between polls; the cursor then
    finds the newest lines it already handed out and continues after them. If
    none of those is left (more output arrived between two polls than the
    server keeps), the gap is marked by handing out the notice itself, followed
    by what remains.
    """

    def __init__(self) -> None:
        self._seen = 0
        self._tail: List[str] = []

    def new_lines(self, logs: List[str]) -> List[str]:
        if not logs or logs[0] != BUILD_LOG_TRUNCATION_NOTICE:
            new = logs[self._seen :]
        else:
            new = self._after_tail(logs)
        self._seen = len(logs)
        self._tail = (self._tail + new)[-_LOG_ANCHOR_LINES:]
        return new

    def _after_tail(self, logs: List[str]) -> List[str]:
        window = logs[1:]
        n = len(self._tail)
        if n:
            for end in range(len(window), n - 1, -1):
                if window[end - 1] == self._tail[-1] and window[end - n : end] == self._tail:
                    return window[end:]
        return logs


class _BuildWatcher:
    """Everything ``Template.build`` decides while it waits, shared by the sync
    and async clients so that only sleeping and the status request differ."""

    def __init__(
        self,
        info: BuildInfo,
        build_timeout: float,
        on_build_logs: Optional[Callable[[str], None]],
    ) -> None:
        self._info = info
        self._build_timeout = build_timeout
        self._deadline = time.monotonic() + build_timeout
        self._on_build_logs = on_build_logs
        self._cursor = _LogCursor()
        self._failing_since: Optional[float] = None

    @property
    def poll_interval(self) -> float:
        return BUILD_POLL_INTERVAL

    @property
    def status_path(self) -> str:
        return f"/templates/builds/{self._info.build_id}"

    def start(self) -> Optional[BuildInfo]:
        """Take the response to starting the build (see ``observe``)."""
        info = self._info
        return self.observe(
            TemplateBuildStatus(
                build_id=info.build_id,
                status=info.status,
                logs=info.logs,
                template_id=info.template_id,
            )
        )

    def observe(self, status: TemplateBuildStatus) -> Optional[BuildInfo]:
        """Take a fresh status: pass on its new log lines, then return the
        finished build, raise ``BuildError`` if it failed or ``TimeoutError``
        past the deadline, or return None to keep waiting."""
        self._failing_since = None
        if self._on_build_logs:
            for line in self._cursor.new_lines(status.logs):
                self._on_build_logs(line)
        if status.status == BUILD_STATUS_COMPLETED:
            return BuildInfo(
                build_id=status.build_id,
                status=status.status,
                template_id=status.template_id or self._info.template_id,
                logs=status.logs,
            )
        if status.status == BUILD_STATUS_FAILED:
            raise build_failed_error(status)
        self._check_deadline()
        return None

    def poll_failed(self, err: Exception) -> None:
        """Take a failed status check. Re-raise it unless it is temporary: keep
        waiting through temporary failures for up to BUILD_POLL_ERROR_WINDOW,
        and never past the deadline."""
        if isinstance(err, _REJECTIONS) or not isinstance(
            err, (SandboxError, httpx.TransportError)
        ):
            raise err
        now = time.monotonic()
        if self._failing_since is None:
            self._failing_since = now
        if now - self._failing_since >= BUILD_POLL_ERROR_WINDOW:
            raise err
        self._check_deadline(err)

    def _check_deadline(self, cause: Optional[BaseException] = None) -> None:
        if time.monotonic() >= self._deadline:
            build_id = self._info.build_id
            raise TimeoutError(
                f"template build {build_id} was still running after "
                f"{self._build_timeout:g}s. It keeps running; follow it with "
                f"get_build_status({build_id!r})."
            ) from cause
