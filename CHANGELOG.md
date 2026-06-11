# Changelog

All notable changes to the Declaw Python SDK are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0]

_2026-06 train: file-granular volumes, OPA governance._

### Added

- Mode-based volumes: write-back and mount modes with a file-granular
  backend, plus a detached volume-files API — `volume.files.write()` /
  `read()` / `list()` / `info()` / `exists()` / `remove()` / `rename()` /
  `mkdir()`, `volumes.empty()` and `volumes.ingest()` constructors, and
  volume locks (`acquire` / `renew` / `release` / `status`) (#344).
- OPA custom-policy support for AI agents: custom policy config with
  `policy_ref` resolution, `content_gate` for model/domain gating, and
  out-of-box AI governance packs via `GovernancePacks` (#279, #345).

### Changed

- The per-sandbox audit flag now gates network, command, and filesystem
  event categories: `enabled=False` suppresses all gated categories
  while lifecycle and admin events are still recorded (#332).

## [1.2.0]

### Added

- `sandbox.stdio.start(cmd)` — native interactive stdio for sandboxed
  processes. Returns a `StdioProcess` handle with `send_stdin()`,
  `close_stdin()`, `stream()`, `kill()`, and `wait()`. Supports
  callbacks (`on_stdout`, `on_stderr`), iterator protocol, and async
  via `AsyncSandbox.stdio`. Use cases: MCP servers, LSP servers, REPLs,
  database shells, any subprocess needing bidirectional stdio.

### Fixed

- HTTP/2 deadlock when using stdio/PTY callbacks with concurrent stdin
  writes. SSE streams now use a dedicated HTTP connection pool,
  preventing flow-control contention with request/response calls on
  the shared connection.

## [1.1.9]

### Fixed

- `create_snapshot()` on both `Sandbox` and `AsyncSandbox` was POSTing
  to `/sandboxes/{id}/snapshots` (plural) instead of the correct
  `/sandboxes/{id}/snapshot` (singular), causing a 404 on every call.
  Broken since 1.0.0. Fixes #303.

## [1.1.8]

### Documentation

- `Filesystem.write` / `AsyncSandbox.write_file`: docstring clarifies
  that `path` is the literal absolute path inside the sandbox — no
  remapping, no bridge directory, no prefix.

## [1.1.7]

### Added

- `Sandbox.kill_by_id(id)` / `AsyncSandbox.kill_by_id(id)` — kill by
  id in one HTTP call.

## [1.1.6]

### Added

- `Sandbox.kill_many(ids)` / `AsyncSandbox.kill_many(ids)` — bulk
  teardown in one request.

### Changed

- `kill()` returns once the kill is accepted; pass `wait=True` to
  block until teardown finishes.

## [1.1.5]

### Changed

- Set httpx connection pool size to 64 (overridable via
  `DECLAW_SDK_CONNECTIONS`).

## [1.1.4]

### Changed

- Enable HTTP/2 on the httpx clients. Adds the `h2` dep via `httpx[http2]`.

## [1.1.3]

### Changed

- **Version bump only** — published alongside TS SDK 1.1.2 to keep the
  release cadence in sync. No code or behavior changes relative to
  1.1.2; the Python binary read path was already correct.

## [1.1.2]

### Fixed

- **Critical fix for 1.1.1.** `AsyncSandbox.list` and `AsyncSandbox.restore`
  were still closing the shared async HTTP client after the call
  (leftover `await client.aclose()` / `await client.close()` from the
  pre-1.1.1 code), which shut down the process-wide connection pool
  and made every subsequent `AsyncSandbox.create` / `AsyncVolumes.*` /
  `AsyncTemplate.*` call fail with `RuntimeError: Cannot send a
  request, as the client has been closed`. Both call sites now leave
  the shared client alone. The sync counterparts were already correct.

## [1.1.1]

### Changed

- **Process-wide HTTP connection pool.** Hot class-method paths
  (`Sandbox.create` / `.list` / `.connect`, `AsyncSandbox.*`, `Volumes.*`,
  `AsyncVolumes.*`, `Template.*`, `AsyncTemplate.*`) now share a single
  `ApiClient` per `(api_key, api_url, request_timeout)` keyed cache
  instead of opening a fresh `httpx.Client` per call. For a loop of 10
  `Sandbox.create` calls this eliminates 9 TCP + TLS handshakes —
  measured drop from ~500 ms per call to ~85 ms after the first, when
  measured from inside the same region as the sandbox-manager. No
  caller code changes required; the cache is transparent.
- `Sandbox.close()` / `AsyncSandbox.close()` are now no-ops WRT the
  HTTP client (the shared pool owns its lifetime). Context-manager
  patterns (`with Sandbox.create() as sbx:`, `async with`) still work
  unchanged because `kill()` remains the actual VM teardown. Call
  `declaw.api.client.reset_shared_clients()` or
  `declaw.api.async_client.reset_async_shared_clients()` (same event
  loop) to force a socket release.
- New exports: `declaw.api.client.get_shared_client`,
  `reset_shared_clients`; `declaw.api.async_client.get_shared_async_client`,
  `reset_async_shared_clients`. `_RawBody` type alias on `ApiClient`
  content parameter widened to `bytes | str | Iterable[bytes] |
  AsyncIterable[bytes] | BinaryIO` so streaming uploads keep typing
  strict.

## [1.1.0]

### Added

- **Volumes API.** Upload a tarball once, attach it to one or many
  sandboxes at create time. The server streams the blob from object
  storage into each sandbox's overlay filesystem at boot — so N
  parallel sandboxes share a dataset without N uploads.
  - New exports: `Volume`, `Volumes`, `AsyncVolumes`, `VolumeAttachment`
    from the package root (and re-exported from `declaw.openai`).
  - `Volumes.create(name, data, ...)` accepts `bytes`, a binary
    file-like object, an iterable of byte chunks, or a path-like
    pointing at a file or directory (auto-tar+gzip for convenience).
    Pairs of `get`, `list`, `delete` for catalog operations.
  - `Sandbox.create(volumes=[VolumeAttachment(volume_id, mount_path)])`
    on both the sync and async sandboxes, and on
    `DeclawSandboxClientOptions.volumes` in the OpenAI Agents backend.
  - Phase 1 limits: upload body capped at 4 GiB; format must be
    `application/gzip` (tar.gz); volumes are read-at-boot (sandbox
    writes do not flow back). Symlinks, hardlinks, device nodes, and
    entries containing `..` are dropped server-side for safety.
- **`py.typed` marker** (PEP 561). Type checkers now use the SDK's
  inline annotations without falling back to `Any`.

### Changed

- Typing polish in the PTY handles: `asyncio.Task[None]`,
  `asyncio.Queue[Optional[bytes]]`, `queue.Queue[Optional[bytes]]` —
  previously unparameterized. No runtime behaviour change.
- `ApiClient.stream()` / `AsyncApiClient.stream()` now declare an
  explicit `-> Any` return annotation (was implicit).
- Optional-dependency extra renamed: `pip install "declaw[openai]"`
  is now `pip install "declaw[openai-agents]"` so the install line
  matches the `declaw.openai` subpackage name. Code importing from
  `declaw.openai` is unaffected; only the install command changes.

## [1.0.4]

### Added

- **`declaw.openai` — OpenAI Agents SDK backend.** Install with
  `pip install "declaw[openai-agents]"` to pull in the `openai-agents`
  dependency. Exposes `DeclawSandboxClient`, `DeclawSandboxClientOptions`,
  `DeclawSandboxSession`, `DeclawSandboxSessionState`,
  `DeclawSandboxTimeouts`, and `DeclawSandboxType`. The options model
  covers the full declaw security surface (`SecurityPolicy`, `PIIConfig`,
  `InjectionDefenseConfig`, `ToxicityConfig`, `CodeSecurityConfig`,
  `InvisibleTextConfig`, `EnvSecurityConfig`, `AuditConfig`,
  `TransformationRule`, `NetworkPolicy`, `SandboxLifecycle`), so agents
  built on the OpenAI Agents SDK get the platform's full guardrails —
  PII redaction, prompt-injection detection, toxicity / code-security /
  invisible-text scanning, per-sandbox network policy, audit logging
  — by setting the same knobs they already use with
  `Sandbox.create(security=...)`. The client-side `PIIHandler` and
  `GuardrailsClient` are re-exported from `declaw.openai` for
  convenience when an agent wants to anonymize prompts before the LLM
  call.
- **`AsyncPty`** — async counterpart to the sync `Pty` module.
  `AsyncSandbox.pty.create(...)` returns an `AsyncPtyHandle` with the
  same surface as the sync handle: `send_stdin`, `resize`, `disconnect`,
  `kill`, `wait`, and `async for chunk in handle:` iteration. Uses
  `httpx.AsyncClient.stream` for SSE consumption.
- `AsyncApiClient.stream()` helper — streaming context manager used
  by the new async PTY path.

### Changed

- Bump to Python SDK 1.0.4. `declaw.openai` is an additive optional
  module gated by the new `[openai-agents]` extra.
- `InjectionDefenseConfig` — dropped the `"sanitize"` action. The
  server never implemented request-body sanitization for detected
  injections (the classifier returns a whole-request verdict, not
  span offsets), so the value was accepted client-side but silently
  behaved like `log_only` at the edge proxy. Valid values are now
  `"block"` and `"log_only"`. Default action changes from
  `"sanitize"` to `"log_only"` so existing enforcement behaviour is
  preserved. Callers passing `action="sanitize"` will now raise at
  construction time; migrate to `"log_only"` (same behaviour) or
  `"block"` (hard-reject on detection).

## [1.0.2]

### Added

- **Interactive PTY streaming** (`sandbox.pty.create()` now returns a
  `PtyHandle`): real-time output via SSE with two consumption modes —
  iterator (`for chunk in handle: ...`) and callback (`on_data=`).
  `PtyHandle` exposes `send_stdin()`, `resize()`, `kill()`, and `wait()`
  for full interactive terminal control. The background reader runs on a
  daemon thread so callers can send input from the main thread while
  receiving output concurrently.
- `ApiClient.stream()` — opens a streaming HTTP response for long-lived
  SSE connections (PTY output streams). No retry semantics — SSE
  connections are reconnected at a higher level.
- `Pty` and `PtyHandle` are now exported from `declaw` top-level.

### Changed

- `Pty.create()` return type changed from `CommandHandle` to `PtyHandle`.
  The legacy low-level methods (`pty.kill(pid)`, `pty.send_stdin(pid)`,
  `pty.resize(pid)`) are retained for back-compat with callers that
  already hold a pid.
- **Audit defaults flipped to on**: `AuditConfig.enabled` now defaults
  to `True` (was `False`), matching platform behavior where lifecycle
  and security events are always recorded unless explicitly opted out.
  `SecurityPolicy.audit` default changed from `False` to `True`.
- `AuditConfig` simplified to a single `enabled` field. Removed
  `log_request_body`, `log_response_body`, and `retention_hours` —
  these were not wired to the backend and retention is a platform-wide
  setting (7-day default via `AUDIT_RETENTION_DAYS`).

## [1.0.1]

### Fixed

- **Binary file writes** (`Filesystem.write()`, `AsyncSandbox.write_file()`,
  `write_files()`): `bytes` payloads were being `utf-8`-decoded with
  `errors="replace"` before JSON serialization, turning every non-UTF-8
  byte into U+FFFD — PNGs, tarballs, and base64-decoded payloads landed
  corrupted. Bytes are now dispatched to the binary-safe
  `PUT /files/raw` endpoint; `str` continues on `POST /files`.
  `write_files()` partitions mixed batches (`str` → JSON batch, `bytes`
  → raw PUT) and preserves input order. Verified byte-identical
  round-trip for PNG magic, non-UTF-8 bytes, and a 4 KiB random blob on
  both sync and async SDKs against `api.declaw.ai`.

### Added

- `AsyncApiClient.put()` — required by the async binary-write path.

### Internal

- Type-cleanup pass: mypy (`strict`) and ruff now run clean on the whole
  package. No runtime behavior changes — adds `bool(...)` around
  `resp.json().get(...)` returns, types `__exit__`/`__aexit__`
  arguments, and tightens `dict` → `Dict[str, Any]` in the PII handler.

## [1.0.0]

First stable release. The public API described below is covered by
semantic versioning going forward: breaking changes require a major
version bump.

### Added

#### Sandbox lifecycle
- `Sandbox.create()` / `AsyncSandbox.create()` spin up a Firecracker
  microVM from a template in ~sub-second and return a handle scoped to
  the caller's account.
- `sandbox.kill()`, `sandbox.pause()`, `sandbox.resume()` for explicit
  lifecycle control; auto-cleanup via the `timeout` constructor arg.
- `Sandbox.list()` and `SandboxPaginator` (`AsyncSandboxPaginator`) for
  enumerating live sandboxes with pagination.
- `sandbox.snapshot()` / `sandbox.restore()` with `Snapshot` and
  `SnapshotInfo` models; `SnapshotPaginator` for listing.
- `SandboxInfo`, `SandboxState`, `SandboxLifecycle`, `SandboxMetrics`,
  `SandboxQuery` data models.

#### Commands
- `sandbox.commands.run()` synchronous one-shot execution returning
  `CommandResult` (stdout/stderr/exit code/duration).
- `sandbox.commands.run_stream()` for incremental stdout/stderr with
  `Stdout` / `Stderr` event types.
- `CommandHandle` (and `AsyncCommandHandle`) for long-running processes:
  `wait()`, `kill()`, stdin piping, PTY resize.
- `sandbox.pty.*` for interactive PTY sessions with `PtySize` /
  `PtyOutput`.
- `ProcessInfo` model and `sandbox.commands.list()` for inspecting live
  processes.

#### Filesystem
- `sandbox.files.read()`, `sandbox.files.write()`, `sandbox.files.list()`,
  `sandbox.files.exists()`, `sandbox.files.info()`, `sandbox.files.remove()`,
  `sandbox.files.rename()`, `sandbox.files.mkdir()`.
- Streaming large uploads/downloads via `files.write_raw()` /
  `files.read_raw()` (500 MiB request cap).
- Batch writes via `files.write_batch()` accepting `WriteEntry` lists.
- Live directory watching via `sandbox.files.watch()` returning
  `WatchHandle` / `AsyncWatchHandle` with `FilesystemEvent` stream.
- `EntryInfo`, `WriteInfo`, `FileType`, `FilesystemEventType` models.

#### Templates
- `Template` / `AsyncTemplate` for defining custom rootfs images from a
  `TemplateBase`, `CopyItem` list, pip/apt installs, and run commands.
- `template.build()` triggers a Firecracker rootfs build; `BuildInfo`
  and `TemplateBuildStatus` surface build progress.

#### Security policy
Declaw's differentiating surface — opt-in per-sandbox via
`security=SecurityPolicy(...)` on create.

- **PII redaction** (`PIIConfig`, `PIIType`, `RedactionAction`): the
  security proxy redacts PII before outbound traffic leaves the VM and
  can rehydrate on the inbound response (`rehydrate_response=True`).
  Supports SSN, credit card, email, phone, person name, API key, IP
  address, and custom types.
- **Prompt injection defense** (`InjectionDefenseConfig`,
  `InjectionAction`, `InjectionSensitivity`): scans outbound payloads
  with the Guardrails service and blocks, transforms, or audits.
- **Network policy** (`NetworkPolicy`, `ALL_TRAFFIC`): allow-list /
  deny-list egress by domain with wildcard + regex matchers. Cloud
  metadata IPs (`169.254.169.254`) blocked by default.
- **Toxicity scanner** (`ToxicityConfig`).
- **Code security scanner** (`CodeSecurityConfig`) for detecting
  code-injection attempts in agent responses.
- **Invisible text scanner** (`InvisibleTextConfig`) strips Unicode
  invisible characters.
- **Transformation rules** (`TransformationRule`, `TransformDirection`)
  for regex-based inbound / outbound content rewriting.
- **Audit logging** (`AuditConfig`, `AuditEntry`) returns per-sandbox
  audit records via `sandbox.get_audit_log()`.
- **Secure env vars** (`SecureEnvVar`, `EnvSecurityConfig`) plumbs
  secrets into sandboxes without persisting them in logs.

#### Account
- `AccountClient` / `AsyncAccountClient` for account management
  without spinning up a sandbox.
- `AccountOverview`, `AccountInfo`, `WalletInfo`, `DepositInfo`,
  `DailyUsage`, `UsageSummary` for billing and usage data.

#### Errors
Typed exception hierarchy — every error subclasses `SandboxError`
(alias `SandboxException`):
- `AuthenticationException` — invalid or revoked API key.
- `InvalidArgumentException` — request validation failure.
- `NotFoundException` — sandbox / template / snapshot missing.
- `RateLimitException` — account tier rate limit hit.
- `InsufficientBalanceException` — wallet cannot cover the request.
- `TimeoutException` — operation exceeded its deadline.
- `CommandExitException` — command exited non-zero.
- `NotEnoughSpaceException` — sandbox disk full.
- `FileUploadException`, `BuildException`, `TemplateException`,
  `GitAuthException`, `GitUpstreamException`.

#### API client
- `ApiClient` / `AsyncApiClient` for advanced users who want to bypass
  the high-level `Sandbox` facade and call the control-plane REST API
  directly.
- `ConnectionConfig` centralizes `DECLAW_API_KEY`, `DECLAW_DOMAIN`,
  timeouts, and debug mode; everything is override-able at
  `Sandbox.create()`.

### Requirements
- Python `>=3.10`
- `httpx >=0.27.0`, `pydantic >=2.0.0`, `packaging >=23.0`
