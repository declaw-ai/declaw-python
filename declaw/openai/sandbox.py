"""Declaw sandbox backend for the OpenAI Agents SDK.

Implements the pluggable sandbox interface from ``agents.sandbox.session``
so that any agent built on the Agents SDK can execute its bash / file /
PTY tools inside a declaw sandbox — with declaw's full security posture
(PII redaction, prompt-injection detection, toxicity scanning,
code-security scanning, invisible-text stripping, network allow/deny,
audit logging, env-var masking) applied via the same ``SecurityPolicy``
surface the core declaw SDK uses.
"""

from __future__ import annotations

import datetime as _dt
import io
import uuid as _uuid
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Union

if TYPE_CHECKING:
    # Keep the real import inside function bodies (deferred + lazy); this
    # block is only read by type checkers and ruff's undefined-name pass.
    from agents.sandbox.session.pty_types import PtyExecUpdate

# Imports from openai-agents — guarded in `declaw/openai/__init__.py`,
# so by the time this module loads we know the package is installed.
from agents.sandbox.manifest import Manifest
from agents.sandbox.session.base_sandbox_session import BaseSandboxSession
from agents.sandbox.session.sandbox_client import (
    BaseSandboxClient,
    BaseSandboxClientOptions,
)
from agents.sandbox.session.sandbox_session import SandboxSession
from agents.sandbox.session.sandbox_session_state import SandboxSessionState
from agents.sandbox.snapshot import SnapshotBase, SnapshotSpec, resolve_snapshot
from agents.sandbox.types import ExecResult, User
from pydantic import BaseModel, ConfigDict, Field

# Declaw SDK surface.
from declaw.exceptions import CommandExitException
from declaw.sandbox.commands.models import CommandResult, ProcessInfo
from declaw.sandbox.filesystem.models import EntryInfo, WriteInfo
from declaw.sandbox.models import (
    SandboxInfo,
    SandboxLifecycle,
    SandboxMetrics,
)
from declaw.sandbox.models import (
    Snapshot as DeclawSnapshot,
)
from declaw.sandbox.network import SandboxNetworkOpts
from declaw.sandbox_async.main import AsyncSandbox
from declaw.sandbox_async.pty import AsyncPty
from declaw.security import (
    AuditConfig,
    CodeSecurityConfig,
    EnvSecurityConfig,
    InjectionDefenseConfig,
    InvisibleTextConfig,
    PIIConfig,
    SecurityPolicy,
    ToxicityConfig,
    TransformationRule,
)
from declaw.volumes.main import VolumeAttachment

# ------------------------------------------------------------------------
# Public enums and orthogonal config
# ------------------------------------------------------------------------


class DeclawSandboxType(str, Enum):
    """Backend runtime selector for a declaw sandbox.

    Only ``DEFAULT`` ships today. The enum is exposed so callers who
    write ``DeclawSandboxType.DEFAULT`` stay forward-compatible if a
    second runtime tier is added in the future.
    """

    DEFAULT = "default"


class DeclawSandboxTimeouts(BaseModel):
    """Orthogonal internal op-timeouts for the adapter.

    Separate from the sandbox lifetime (``DeclawSandboxClientOptions.timeout``)
    — these control how long individual adapter-internal calls wait.
    """

    model_config = ConfigDict(frozen=True)

    # Per-command exec cap. Unbounded by default; callers set a lower
    # value when the agent's bash tool could run forever.
    exec_timeout_s: int = Field(default=0, ge=0)
    # Fast metadata ops (info, is_running, ls).
    fast_op_s: int = Field(default=10, ge=1)
    # File upload / download.
    file_io_s: int = Field(default=60, ge=1)
    # Snapshot create / list.
    snapshot_s: int = Field(default=120, ge=1)


# ------------------------------------------------------------------------
# Options model — the full declaw surface exposed to Agents-SDK callers
# ------------------------------------------------------------------------


class DeclawSandboxClientOptions(BaseSandboxClientOptions):
    """Client options for the declaw sandbox backend.

    Exposes every knob the declaw ``Sandbox.create`` API takes, including
    the full ``SecurityPolicy`` surface. Individual security sub-configs
    (``pii``, ``injection_defense``, etc.) can be passed directly for
    convenience — any set field overrides its counterpart on the
    composite ``security`` policy.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    # Discriminator — triggers auto-registration in BaseSandboxClientOptions.
    type: Literal["declaw"] = "declaw"

    # --- Core sandbox config ---
    template: str = "base"
    api_key: Optional[str] = None
    domain: Optional[str] = None
    timeout: Optional[int] = 300
    envs: Optional[Dict[str, str]] = None
    metadata: Optional[Dict[str, str]] = None
    allow_internet_access: bool = True

    # --- Full security surface ---
    security: Optional[SecurityPolicy] = None
    pii: Optional[PIIConfig] = None
    injection_defense: Optional[InjectionDefenseConfig] = None
    transformations: Optional[List[TransformationRule]] = None
    toxicity: Optional[ToxicityConfig] = None
    code_security: Optional[CodeSecurityConfig] = None
    invisible_text: Optional[InvisibleTextConfig] = None
    env_security: Optional[EnvSecurityConfig] = None
    audit: Optional[AuditConfig] = None

    # --- Network isolation ---
    network: Optional[SandboxNetworkOpts] = None

    # --- Volumes ---
    # Pre-uploaded blobs (created via declaw.Volumes.create) to hydrate into
    # the sandbox filesystem before the agent's first tool call. Each entry
    # is either a VolumeAttachment(volume_id, mount_path) or a plain dict
    # with the same keys. The attach list is deduplicated server-side.
    volumes: Optional[List[Union[VolumeAttachment, Dict[str, str]]]] = None

    # --- Lifecycle / timeouts ---
    lifecycle: Optional[SandboxLifecycle] = None
    timeouts: Optional[DeclawSandboxTimeouts] = None


def _compose_security(options: DeclawSandboxClientOptions) -> Optional[SecurityPolicy]:
    """Merge ``options.security`` with per-field shortcuts.

    Rule: if the user passed a full ``SecurityPolicy`` we start from it;
    any individual ``options.pii`` / ``options.injection_defense`` / ...
    field that is non-None overrides the matching sub-config. If neither
    the policy nor any shortcut is set, returns ``None`` so the sandbox
    uses platform defaults.
    """
    shortcuts_set = any(
        getattr(options, name) is not None
        for name in (
            "pii",
            "injection_defense",
            "transformations",
            "toxicity",
            "code_security",
            "invisible_text",
            "env_security",
            "audit",
        )
    )
    if options.security is None and not shortcuts_set:
        return None

    policy = options.security or SecurityPolicy()
    if options.pii is not None:
        policy.pii = options.pii
    if options.injection_defense is not None:
        policy.injection_defense = options.injection_defense
    if options.transformations is not None:
        policy.transformations = options.transformations
    if options.toxicity is not None:
        policy.toxicity = options.toxicity
    if options.code_security is not None:
        policy.code_security = options.code_security
    if options.invisible_text is not None:
        policy.invisible_text = options.invisible_text
    if options.env_security is not None:
        policy.env_security = options.env_security
    if options.audit is not None:
        policy.audit = options.audit
    # A policy-level network is held separately on the declaw Sandbox call.
    return policy


# ------------------------------------------------------------------------
# Session state — what we persist so resume() can reattach
# ------------------------------------------------------------------------


class DeclawSandboxSessionState(SandboxSessionState):
    """Serializable state for a declaw session.

    Carries the opaque ``sandbox_id`` for direct reattach and, when the
    session was snapshotted via ``persist_workspace``, the
    ``snapshot_id`` pointing at the declaw memory+disk checkpoint.
    """

    type: Literal["declaw"] = "declaw"
    sandbox_id: str
    snapshot_id: Optional[str] = None
    template: str = "base"
    created_at: _dt.datetime = Field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc))
    # Carried for resume: we don't have the full options at that point,
    # but we need enough to recreate a usable session.
    base_envs: Dict[str, str] = Field(default_factory=dict)


# ------------------------------------------------------------------------
# Session — wraps an AsyncSandbox and implements the ABC contract
# ------------------------------------------------------------------------


class DeclawSandboxSession(BaseSandboxSession):
    """BaseSandboxSession implementation backed by ``declaw.AsyncSandbox``.

    Every abstract method of the Agents SDK session ABC is delegated to
    the matching AsyncSandbox call. On top of the ABC contract, this
    class also exposes declaw-specific conveniences: snapshots,
    metrics, pause/resume, set_timeout, streaming + background command
    execution, batch file writes, file info/exists/rename, and direct
    access to the underlying AsyncSandbox.
    """

    state: DeclawSandboxSessionState

    def __init__(
        self,
        *,
        state: DeclawSandboxSessionState,
        sandbox: AsyncSandbox,
    ) -> None:
        super().__init__()
        self.state = state
        self._sbx = sandbox
        # Map Agents-SDK pty process_id -> declaw AsyncPtyHandle. Populated
        # by pty_exec_start; drained by pty_terminate_all. Keyed by the
        # process id the SDK allocates, not the in-VM OS pid.
        self._pty_handles: Dict[int, Any] = {}
        self._pty_buffers: Dict[int, bytearray] = {}

    @classmethod
    def from_state(
        cls,
        state: DeclawSandboxSessionState,
        *,
        sandbox: AsyncSandbox,
    ) -> "DeclawSandboxSession":
        """Construct a session from a state + live sandbox handle.

        Used by resume paths where the state was serialized and the
        live sandbox was reattached separately.
        """
        return cls(state=state, sandbox=sandbox)

    # ------------------------------------------------------------------
    # Declaw accessors
    # ------------------------------------------------------------------

    @property
    def sandbox_id(self) -> str:
        return self._sbx.sandbox_id

    @property
    def underlying_sandbox(self) -> AsyncSandbox:
        """The wrapped ``AsyncSandbox`` — escape hatch for any API this
        adapter doesn't surface directly."""
        return self._sbx

    @property
    def pty(self) -> AsyncPty:
        """The async PTY module for this sandbox.

        Preferred over ``pty_exec_start`` for interactive workflows
        because it gives the caller an ``AsyncPtyHandle`` with a
        callback / iterator surface matching our sync PTY API.
        """
        return self._sbx.pty

    # ------------------------------------------------------------------
    # Declaw-only sandbox lifecycle conveniences
    # ------------------------------------------------------------------

    async def info(self) -> SandboxInfo:
        """Fetch full sandbox info (template, state, envd_access_token, etc.)."""
        return await self._sbx.get_info()

    async def set_timeout(self, timeout: int) -> None:
        """Extend (or shorten) the sandbox's TTL while it's live."""
        await self._sbx.set_timeout(timeout)

    async def pause(self) -> None:
        """Pause the sandbox so it can be resumed later from a snapshot."""
        await self._sbx.pause()

    async def resume_sandbox(self) -> None:
        """Resume a previously paused sandbox.

        Named ``resume_sandbox`` (not ``resume``) to avoid colliding
        with the Agents SDK's ``BaseSandboxClient.resume`` lifecycle
        hook that restores a session from serialized state.
        """
        await self._sbx.resume()

    async def metrics(
        self,
        start: Optional[_dt.datetime] = None,
        end: Optional[_dt.datetime] = None,
    ) -> List[SandboxMetrics]:
        """CPU / memory / disk usage time series."""
        return await self._sbx.get_metrics(start=start, end=end)

    async def list_snapshots(self) -> List[DeclawSnapshot]:
        return await self._sbx.list_snapshots()

    async def snapshot(self) -> DeclawSnapshot:
        """Explicit declaw snapshot — richer than the ABC's
        ``persist_workspace`` return shape."""
        return await self._sbx.snapshot()

    # ------------------------------------------------------------------
    # Declaw-only command helpers (streaming + background)
    # ------------------------------------------------------------------

    async def run_stream(
        self,
        command: str,
        *,
        on_stdout: Optional[Callable[[str], None]] = None,
        on_stderr: Optional[Callable[[str], None]] = None,
        envs: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        user: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Run a command and stream stdout/stderr lines to callbacks as they arrive."""
        return await self._sbx.run_command(
            command,
            on_stdout=on_stdout,
            on_stderr=on_stderr,
            envs=envs,
            cwd=cwd,
            user=user or "user",
            timeout=timeout,
        )

    async def run_background(
        self,
        command: str,
        *,
        envs: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        user: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Start a long-running process; returns an ``AsyncCommandHandle``."""
        return await self._sbx.run_command(
            command,
            background=True,
            envs=envs,
            cwd=cwd,
            user=user or "user",
            timeout=timeout,
        )

    async def list_processes(self) -> List[ProcessInfo]:
        return await self._sbx.list_commands()

    async def kill_process(self, pid: int) -> bool:
        return await self._sbx.kill_command(pid)

    async def send_process_stdin(self, pid: int, data: str) -> None:
        """Forward stdin bytes to a background command."""
        await self._sbx.send_command_stdin(pid, data)

    def connect_process(self, pid: int) -> Any:
        """Reattach to a running background command by pid; returns
        an ``AsyncCommandHandle`` the agent can ``await handle.wait()`` on."""
        return self._sbx.connect_command(pid)

    # ------------------------------------------------------------------
    # Declaw-only file helpers — all backed by AsyncSandbox methods
    # ------------------------------------------------------------------

    async def file_exists(self, path: Union[Path, str]) -> bool:
        return await self._sbx.file_exists(str(path))

    async def file_info(self, path: Union[Path, str]) -> EntryInfo:
        return await self._sbx.get_file_info(str(path))

    async def file_rename(self, src: Union[Path, str], dst: Union[Path, str]) -> EntryInfo:
        return await self._sbx.rename_file(str(src), str(dst))

    async def write_files(self, entries: List[Any]) -> List[WriteInfo]:
        """Batch-write multiple text files in one API call.

        Binary entries aren't supported by the batch endpoint — call
        :meth:`write` per-file for those.
        """
        return await self._sbx.write_files(entries)

    # ------------------------------------------------------------------
    # BaseSandboxSession abstract methods
    # ------------------------------------------------------------------

    async def _exec_internal(
        self,
        *command: Union[str, Path],
        timeout: Optional[float] = None,
    ) -> ExecResult:
        # The Agents SDK pre-sanitizes: `exec("echo", "hi")` with shell=True
        # arrives here as ("sh", "-lc", "echo hi"). declaw's run_command
        # takes a shell-quoted string and always wraps in `sh -c`, so we
        # collapse `("sh", "-lc", <inner>)` to the inner command to avoid
        # a double shell layer that eats positional args. Otherwise
        # shlex-join the argv so each piece is quoted correctly.
        parts = [str(c) for c in command]
        if len(parts) == 3 and parts[0] == "sh" and parts[1] == "-lc":
            cmd = parts[2]
        elif len(parts) == 1:
            cmd = parts[0]
        else:
            import shlex as _shlex

            cmd = _shlex.join(parts)
        try:
            result = await self._sbx.run_command(cmd, timeout=timeout)
        except CommandExitException as exc:
            # Surface as ExecResult with the non-zero exit code rather
            # than raising — the Runner inspects ok()/exit_code to
            # decide how to present the result to the LLM.
            return ExecResult(
                stdout=(exc.stdout or "").encode("utf-8"),
                stderr=(exc.stderr or "").encode("utf-8"),
                exit_code=exc.exit_code,
            )
        # background=False (default) always returns CommandResult, never
        # AsyncCommandHandle — narrow the union for the type checker.
        assert isinstance(result, CommandResult)
        return ExecResult(
            stdout=result.stdout.encode("utf-8"),
            stderr=result.stderr.encode("utf-8"),
            exit_code=result.exit_code,
        )

    async def read(
        self,
        path: Path,
        *,
        user: Optional[Union[str, User]] = None,
    ) -> io.IOBase:
        _ = user
        data = await self._sbx.read_file(str(path), format="bytes")
        if isinstance(data, (bytes, bytearray)):
            return io.BytesIO(bytes(data))
        if isinstance(data, str):
            return io.BytesIO(data.encode("utf-8"))
        # Streaming source (iterable of bytes).
        return io.BytesIO(b"".join(chunk for chunk in data))

    async def write(
        self,
        path: Path,
        data: io.IOBase,
        *,
        user: Optional[Union[str, User]] = None,
    ) -> None:
        _ = user
        payload: Union[bytes, str]
        if hasattr(data, "read"):
            payload = data.read()
        else:
            payload = data  # type: ignore[assignment]
        await self._sbx.write_file(str(path), payload)

    async def running(self) -> bool:
        try:
            return await self._sbx.is_running()
        except Exception:
            return False

    async def persist_workspace(self) -> io.IOBase:
        """Create a declaw snapshot; the ``snapshot_id`` is carried on
        the associated ``DeclawSandboxSessionState`` so
        ``resume(state)`` can restore the full VM (memory + disk).

        The ``io.IOBase`` returned here satisfies the ABC contract —
        it carries a small JSON marker for introspection but does not
        contain the actual workspace bytes; declaw stores those
        server-side in the platform's blob store.
        """
        snap = await self._sbx.snapshot()
        self._last_snapshot_id = snap.snapshot_id
        marker = f'{{"declaw_snapshot_id":"{snap.snapshot_id}"}}'.encode("utf-8")
        return io.BytesIO(marker)

    async def hydrate_workspace(self, data: io.IOBase) -> None:
        """No-op. Declaw hydration happens inside
        ``DeclawSandboxClient.resume`` via the state's ``snapshot_id``;
        there is no per-file tar to apply on top of a restored VM."""
        _ = data
        return None

    # ------------------------------------------------------------------
    # Overrides for performance — use declaw's direct files API instead
    # of the default exec-based implementations.
    # ------------------------------------------------------------------

    async def ls(  # type: ignore[override]
        self,
        path: Union[Path, str],
        *,
        user: Optional[Union[str, User]] = None,
    ) -> List[EntryInfo]:
        _ = user
        return await self._sbx.list_files(str(path))

    async def mkdir(
        self,
        path: Union[Path, str],
        *,
        parents: bool = False,
        user: Optional[Union[str, User]] = None,
    ) -> None:
        _ = (parents, user)
        await self._sbx.make_dir(str(path))

    async def rm(
        self,
        path: Union[Path, str],
        *,
        recursive: bool = False,
        user: Optional[Union[str, User]] = None,
    ) -> None:
        _ = (recursive, user)
        await self._sbx.remove_file(str(path))

    # ------------------------------------------------------------------
    # Capability hints
    # ------------------------------------------------------------------

    def supports_docker_volume_mounts(self) -> bool:
        return False

    def supports_pty(self) -> bool:
        # The Agents SDK's shell tool prefers the PTY path when this is
        # True, so interactive programs (progress bars, curses, stdin-
        # driven prompts) work natively inside the agent's turn. Per-
        # command PTY audit events are the documented contract of that
        # path, not noise.
        return True

    # ------------------------------------------------------------------
    # PTY surface required by the ABC (pty_exec_start /
    # pty_write_stdin / pty_terminate_all). Backed by declaw's
    # AsyncPty; the native surface is still available via ``session.pty``.
    # ------------------------------------------------------------------

    async def pty_exec_start(
        self,
        *command: Union[str, Path],
        timeout: Optional[float] = None,
        shell: Union[bool, List[str]] = True,
        user: Optional[Union[str, User]] = None,
        tty: bool = False,
        yield_time_s: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
    ) -> "PtyExecUpdate":
        from agents.sandbox.session.pty_types import (
            PTY_PROCESSES_MAX,
            PtyExecUpdate,
            allocate_pty_process_id,
            truncate_text_by_tokens,
        )

        _ = (shell, user, tty)  # declaw's PTY always shells via bash -l

        # Cap concurrent PTYs per session — keeps the agent from leaking.
        if len(self._pty_handles) >= PTY_PROCESSES_MAX:
            # Reap any that have already exited before rejecting.
            for pid in list(self._pty_handles):
                handle = self._pty_handles[pid]
                if getattr(handle, "exit_code", None) is not None:
                    self._pty_handles.pop(pid, None)
                    self._pty_buffers.pop(pid, None)

        process_id = allocate_pty_process_id(set(self._pty_handles.keys()))
        buf = bytearray()
        self._pty_buffers[process_id] = buf

        def _on_data(chunk: bytes) -> None:
            buf.extend(chunk)

        # Pass the sandbox-level envs explicitly — older sandbox-manager
        # builds don't merge sbx.Envs into PTY create requests the way
        # they do for command/run paths, so the agent's printenv would
        # miss vars configured on the session. Passing them per-call is
        # safe with any server version.
        handle = await self._sbx.pty.create(
            on_data=_on_data,
            envs=(self.state.base_envs or None),
            timeout=(timeout if timeout and timeout > 0 else None),
        )
        self._pty_handles[process_id] = handle

        # Wait for the bash prompt to appear before injecting the
        # command — if we send_stdin before bash is ready, the bytes
        # get swallowed by the terminal line buffer and the command
        # never runs. Poll until we see non-empty output (the banner /
        # prompt) or a safety timeout trips.
        import asyncio as _asyncio

        prompt_wait = 0.0
        while prompt_wait < 5.0 and len(buf) == 0:
            await _asyncio.sleep(0.1)
            prompt_wait += 0.1
        # Drop whatever the banner was — we only want the command output.
        buf.clear()

        # Feed the command in. Joined because AsyncPty takes raw stdin
        # bytes and the SDK hands us variadic args.
        cmd_str = " ".join(str(c) for c in command) + "\n"
        await handle.send_stdin(cmd_str.encode("utf-8"))

        # Wait for output to settle. Poll the buffer for fresh bytes —
        # return once we see output followed by a quiet window, or when
        # the yield_time_s / default budget elapses. This prevents
        # returning an empty buffer for commands that need more than the
        # SDK's default yield before the first chunk arrives.
        import asyncio as _asyncio

        budget = yield_time_s if yield_time_s else 2.0
        poll_interval = 0.05
        quiet_window = 0.3
        elapsed = 0.0
        last_len = 0
        last_growth_at = 0.0
        while elapsed < budget:
            await _asyncio.sleep(poll_interval)
            elapsed += poll_interval
            if len(buf) != last_len:
                last_len = len(buf)
                last_growth_at = elapsed
                continue
            if last_len > 0 and (elapsed - last_growth_at) >= quiet_window:
                break

        output = bytes(buf)
        buf.clear()
        truncated, original_token_count = truncate_text_by_tokens(
            output.decode("utf-8", errors="replace"),
            max_output_tokens,
        )
        return PtyExecUpdate(
            process_id=process_id,
            output=truncated.encode("utf-8"),
            exit_code=handle.exit_code,
            original_token_count=original_token_count,
        )

    async def pty_write_stdin(
        self,
        *,
        session_id: int,
        chars: str,
        yield_time_s: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
    ) -> "PtyExecUpdate":
        from agents.sandbox.session.pty_types import (
            PtyExecUpdate,
            truncate_text_by_tokens,
        )

        handle = self._pty_handles.get(session_id)
        if handle is None:
            raise KeyError(f"no active PTY with session_id={session_id}")

        if chars:
            await handle.send_stdin(chars.encode("utf-8"))

        import asyncio as _asyncio

        await _asyncio.sleep(yield_time_s if yield_time_s else 0.1)

        buf = self._pty_buffers.setdefault(session_id, bytearray())
        output = bytes(buf)
        buf.clear()

        # Clean up if the remote shell exited while we waited.
        if getattr(handle, "exit_code", None) is not None:
            self._pty_handles.pop(session_id, None)
            self._pty_buffers.pop(session_id, None)

        truncated, original_token_count = truncate_text_by_tokens(
            output.decode("utf-8", errors="replace"),
            max_output_tokens,
        )
        return PtyExecUpdate(
            process_id=session_id,
            output=truncated.encode("utf-8"),
            exit_code=getattr(handle, "exit_code", None),
            original_token_count=original_token_count,
        )

    async def pty_terminate_all(self) -> None:
        for pid, handle in list(self._pty_handles.items()):
            try:
                await handle.kill()
            except Exception:
                pass
            self._pty_handles.pop(pid, None)
            self._pty_buffers.pop(pid, None)


# ------------------------------------------------------------------------
# Client — lifecycle operations
# ------------------------------------------------------------------------


class DeclawSandboxClient(BaseSandboxClient[DeclawSandboxClientOptions]):
    """Sandbox client that creates declaw sandboxes for agent execution."""

    backend_id = "declaw"
    supports_default_options = True

    async def create(
        self,
        *,
        snapshot: Optional[Union[SnapshotSpec, SnapshotBase]] = None,
        manifest: Optional[Manifest] = None,
        options: DeclawSandboxClientOptions,
    ) -> SandboxSession:
        manifest = manifest or Manifest()
        base_envs = dict(options.envs or {})
        manifest_envs = await manifest.environment.resolve()
        envs = {**base_envs, **manifest_envs} or None

        sbx = await AsyncSandbox.create(
            template=options.template,
            timeout=options.timeout,
            envs=envs,
            metadata=options.metadata,
            security=_compose_security(options),
            network=options.network,
            lifecycle=options.lifecycle,
            volumes=list(options.volumes) if options.volumes else None,
            allow_internet_access=options.allow_internet_access,
            api_key=options.api_key,
            domain=options.domain,
        )

        session_id = _uuid.uuid4()
        # The Agents SDK's tar-based snapshot plumbing isn't used by
        # declaw (our snapshots are memory+disk, tracked by snapshot_id
        # on the state), but we still have to populate `state.snapshot`
        # with a valid SnapshotBase so the ABC's lifecycle hooks that
        # touch it do not fault.
        snapshot_instance = resolve_snapshot(snapshot, str(session_id))
        state = DeclawSandboxSessionState(
            session_id=session_id,
            sandbox_id=sbx.sandbox_id,
            template=options.template,
            base_envs=base_envs,
            snapshot=snapshot_instance,
            manifest=manifest,
        )
        inner = DeclawSandboxSession.from_state(state, sandbox=sbx)
        return self._wrap_session(inner)

    async def delete(self, session: SandboxSession) -> SandboxSession:
        inner = _unwrap(session)
        try:
            await inner.underlying_sandbox.kill()
        except Exception:
            # Best-effort cleanup; the sandbox will be reaped by the
            # declaw platform's timeout regardless.
            pass
        return session

    async def resume(self, state: SandboxSessionState) -> SandboxSession:
        if not isinstance(state, DeclawSandboxSessionState):
            raise TypeError(
                "DeclawSandboxClient.resume expects a DeclawSandboxSessionState; "
                f"got {type(state).__name__}"
            )

        if state.snapshot_id is not None:
            # Restore from a previously persisted snapshot.
            sbx = await AsyncSandbox.restore(
                sandbox_id=state.sandbox_id,
                snapshot_id=state.snapshot_id,
            )
        else:
            # Reattach to a live sandbox by id.
            sbx = await AsyncSandbox.connect(state.sandbox_id)

        inner = DeclawSandboxSession.from_state(state, sandbox=sbx)
        return self._wrap_session(inner)

    def deserialize_session_state(
        self,
        payload: Dict[str, object],
    ) -> SandboxSessionState:
        return DeclawSandboxSessionState.model_validate(payload)


def _unwrap(session: SandboxSession) -> DeclawSandboxSession:
    """Extract the inner DeclawSandboxSession from the wrapper SandboxSession.

    The SDK wraps every BaseSandboxSession in an instrumented
    ``SandboxSession`` shell; unwrapping is needed when we need the
    wrapped type to reach declaw-specific methods.
    """
    inner = getattr(session, "_inner", None) or getattr(session, "inner", None) or session
    if not isinstance(inner, DeclawSandboxSession):
        raise TypeError(f"expected DeclawSandboxSession, got {type(inner).__name__}")
    return inner


__all__ = [
    "DeclawSandboxClient",
    "DeclawSandboxClientOptions",
    "DeclawSandboxSession",
    "DeclawSandboxSessionState",
    "DeclawSandboxTimeouts",
    "DeclawSandboxType",
]
