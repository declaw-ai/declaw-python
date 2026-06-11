from __future__ import annotations

from typing import Optional


class SandboxError(Exception):
    """Base exception for all Declaw sandbox errors."""

    def __init__(self, message: str = "", *, sandbox_id: str | None = None):
        self.sandbox_id = sandbox_id
        super().__init__(message)


class TimeoutError(SandboxError):
    """Raised when an operation exceeds its timeout."""


class NotFoundError(SandboxError):
    """Raised when a sandbox or resource is not found."""


class AuthenticationError(SandboxError):
    """Raised when API key or access token is invalid."""


class InvalidArgumentError(SandboxError):
    """Raised when invalid arguments are passed to an API call."""


class NotEnoughSpaceError(SandboxError):
    """Raised when the sandbox runs out of disk space."""


class ConflictError(SandboxError):
    """Raised on a resource conflict (HTTP 409).

    For volume CAS writes this signals the file changed since the
    ``if_version`` token was read — re-read and retry. For volume locks
    it signals the lock is already held / not held by you.
    """


# A CAS write version mismatch is just a 409 conflict; expose a named
# alias so callers can ``except VersionMismatchError`` for clarity.
VersionMismatchError = ConflictError


class TemplateError(SandboxError):
    """Raised on template build or retrieval errors."""


class BuildError(TemplateError):
    """Raised when a template build fails."""


class FileUploadError(SandboxError):
    """Raised when a file upload to the sandbox fails."""


class GitAuthError(SandboxError):
    """Raised on git authentication errors inside the sandbox."""


class GitUpstreamError(SandboxError):
    """Raised on git upstream errors inside the sandbox."""


class CommandExitError(SandboxError):
    """Raised when a command exits with a non-zero exit code."""

    def __init__(
        self,
        message: str = "",
        *,
        exit_code: int = 1,
        stdout: str = "",
        stderr: str = "",
        sandbox_id: str | None = None,
    ):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(message, sandbox_id=sandbox_id)


# Backwards-compatible aliases
SandboxException = SandboxError
TimeoutException = TimeoutError
NotFoundException = NotFoundError
AuthenticationException = AuthenticationError
InvalidArgumentException = InvalidArgumentError
NotEnoughSpaceException = NotEnoughSpaceError
ConflictException = ConflictError
VersionMismatchException = VersionMismatchError
TemplateException = TemplateError
BuildException = BuildError
FileUploadException = FileUploadError
GitAuthException = GitAuthError
GitUpstreamException = GitUpstreamError
CommandExitException = CommandExitError


class InsufficientBalanceException(SandboxException):
    """Raised when account has insufficient balance (HTTP 402)."""

    def __init__(self, message: str = "", wallet_type: str = ""):
        super().__init__(message)
        self.wallet_type = wallet_type


class RateLimitException(SandboxException):
    """Raised when rate limited (HTTP 429)."""

    def __init__(
        self,
        message: str = "",
        retry_after: Optional[float] = None,
        limit: Optional[int] = None,
        remaining: Optional[int] = None,
    ):
        super().__init__(message)
        self.retry_after = retry_after
        self.limit = limit
        self.remaining = remaining
