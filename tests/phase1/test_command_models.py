import json

from declaw import CommandResult, ProcessInfo, PtyOutput, PtySize, Stderr, Stdout


class TestCommandResult:
    def test_defaults(self):
        r = CommandResult()
        assert r.stdout == ""
        assert r.stderr == ""
        assert r.exit_code == 0

    def test_round_trip(self):
        r = CommandResult(stdout="hello\n", stderr="warn\n", exit_code=1)
        restored = CommandResult.from_dict(r.to_dict())
        assert restored.stdout == "hello\n"
        assert restored.stderr == "warn\n"
        assert restored.exit_code == 1

    def test_json_serializable(self):
        r = CommandResult(stdout="ok", exit_code=0)
        s = json.dumps(r.to_dict())
        assert "ok" in s


class TestProcessInfo:
    def test_round_trip(self):
        p = ProcessInfo(pid=42, cmd="python main.py", is_pty=True, envs={"FOO": "bar"})
        restored = ProcessInfo.from_dict(p.to_dict())
        assert restored.pid == 42
        assert restored.cmd == "python main.py"
        assert restored.is_pty is True
        assert restored.envs == {"FOO": "bar"}


class TestPtySize:
    def test_defaults(self):
        s = PtySize()
        assert s.cols == 80
        assert s.rows == 24

    def test_custom(self):
        s = PtySize(cols=120, rows=40)
        d = s.to_dict()
        assert d == {"cols": 120, "rows": 40}


class TestStdoutStderr:
    def test_stdout(self):
        s = Stdout(line="hello world")
        assert s.line == "hello world"

    def test_stderr(self):
        s = Stderr(line="error occurred")
        assert s.line == "error occurred"


class TestPtyOutput:
    def test_default(self):
        p = PtyOutput()
        assert p.data == b""

    def test_with_data(self):
        p = PtyOutput(data=b"terminal output")
        d = p.to_dict()
        assert d["data"] == "terminal output"
