import pytest

from declaw import (
    AuthenticationException,
    BuildException,
    CommandExitException,
    FileUploadException,
    GitAuthException,
    GitUpstreamException,
    InvalidArgumentException,
    NotEnoughSpaceException,
    NotFoundException,
    SandboxException,
    TemplateException,
    TimeoutException,
)


class TestExceptionHierarchy:
    def test_all_inherit_from_sandbox_exception(self):
        for exc_cls in [
            TimeoutException,
            NotFoundException,
            AuthenticationException,
            InvalidArgumentException,
            NotEnoughSpaceException,
            TemplateException,
            BuildException,
            FileUploadException,
            GitAuthException,
            GitUpstreamException,
            CommandExitException,
        ]:
            assert issubclass(exc_cls, SandboxException)

    def test_build_inherits_template(self):
        assert issubclass(BuildException, TemplateException)

    def test_sandbox_exception_with_sandbox_id(self):
        exc = SandboxException("test error", sandbox_id="sbx-123")
        assert exc.sandbox_id == "sbx-123"
        assert str(exc) == "test error"

    def test_sandbox_exception_without_id(self):
        exc = SandboxException("plain error")
        assert exc.sandbox_id is None

    def test_command_exit_exception(self):
        exc = CommandExitException(
            "command failed",
            exit_code=127,
            stdout="out",
            stderr="err",
            sandbox_id="sbx-1",
        )
        assert exc.exit_code == 127
        assert exc.stdout == "out"
        assert exc.stderr == "err"
        assert exc.sandbox_id == "sbx-1"

    def test_command_exit_exception_defaults(self):
        exc = CommandExitException()
        assert exc.exit_code == 1
        assert exc.stdout == ""
        assert exc.stderr == ""

    def test_exceptions_are_catchable(self):
        with pytest.raises(SandboxException):
            raise TimeoutException("timed out")

        with pytest.raises(TemplateException):
            raise BuildException("build failed")
