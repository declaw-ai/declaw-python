import json

import httpx
import pytest
import respx

from declaw import CommandHandle, CommandResult, Sandbox
from declaw.exceptions import CommandExitException

API_URL = "https://api.test.dev"

SANDBOX_RESP = {
    "sandbox_id": "sbx-cmd",
    "template_id": "tpl-base",
    "name": "base",
    "envd_access_token": "tok-1",
    "sandbox_domain": "test.dev",
    "state": "running",
    "metadata": {},
}


@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    monkeypatch.setenv("DECLAW_API_KEY", "test-key")
    monkeypatch.setenv("DECLAW_DOMAIN", "api.test.dev")


def _create_sandbox():
    return Sandbox.create(api_key="test-key", domain="api.test.dev")


class TestCommandsRun:
    @respx.mock
    def test_run_foreground(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-cmd/commands").mock(
            return_value=httpx.Response(
                200,
                json={
                    "stdout": "hello world\n",
                    "stderr": "",
                    "exit_code": 0,
                },
            )
        )
        sandbox = _create_sandbox()
        result = sandbox.commands.run("echo hello world")
        assert isinstance(result, CommandResult)
        assert result.stdout == "hello world\n"
        assert result.exit_code == 0

    @respx.mock
    def test_run_with_envs(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        route = respx.post(f"{API_URL}/sandboxes/sbx-cmd/commands").mock(
            return_value=httpx.Response(
                200,
                json={
                    "stdout": "bar\n",
                    "stderr": "",
                    "exit_code": 0,
                },
            )
        )
        sandbox = _create_sandbox()
        sandbox.commands.run("echo $FOO", envs={"FOO": "bar"})
        req_body = json.loads(route.calls[0].request.content)
        assert req_body["envs"] == {"FOO": "bar"}

    @respx.mock
    def test_run_with_cwd_and_user(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        route = respx.post(f"{API_URL}/sandboxes/sbx-cmd/commands").mock(
            return_value=httpx.Response(
                200,
                json={
                    "stdout": "",
                    "stderr": "",
                    "exit_code": 0,
                },
            )
        )
        sandbox = _create_sandbox()
        sandbox.commands.run("ls", user="root", cwd="/tmp")
        req_body = json.loads(route.calls[0].request.content)
        assert req_body["user"] == "root"
        assert req_body["cwd"] == "/tmp"

    @respx.mock
    def test_run_background(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-cmd/commands").mock(
            return_value=httpx.Response(200, json={"pid": 42})
        )
        sandbox = _create_sandbox()
        handle = sandbox.commands.run("sleep 10", background=True)
        assert isinstance(handle, CommandHandle)
        assert handle.pid == 42

    @respx.mock
    def test_run_on_stdout_callback(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-cmd/commands").mock(
            return_value=httpx.Response(
                200,
                json={
                    "stdout": "line1\nline2\n",
                    "stderr": "",
                    "exit_code": 0,
                },
            )
        )
        sandbox = _create_sandbox()
        lines = []
        sandbox.commands.run("cmd", on_stdout=lambda line: lines.append(line))
        assert len(lines) == 2

    @respx.mock
    def test_run_on_stderr_callback(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-cmd/commands").mock(
            return_value=httpx.Response(
                200,
                json={
                    "stdout": "",
                    "stderr": "warn1\nwarn2\n",
                    "exit_code": 0,
                },
            )
        )
        sandbox = _create_sandbox()
        errs = []
        sandbox.commands.run("cmd", on_stderr=lambda line: errs.append(line))
        assert len(errs) == 2


class TestCommandsList:
    @respx.mock
    def test_list_commands(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.get(f"{API_URL}/sandboxes/sbx-cmd/commands").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"pid": 1, "cmd": "python main.py", "is_pty": False, "envs": {}},
                    {"pid": 2, "cmd": "bash", "is_pty": True, "envs": {}},
                ],
            )
        )
        sandbox = _create_sandbox()
        procs = sandbox.commands.list()
        assert len(procs) == 2
        assert procs[0].pid == 1
        assert procs[1].is_pty is True


class TestCommandsKill:
    @respx.mock
    def test_kill_command(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.delete(f"{API_URL}/sandboxes/sbx-cmd/commands/42").mock(
            return_value=httpx.Response(200, json={"killed": True})
        )
        sandbox = _create_sandbox()
        assert sandbox.commands.kill(42) is True


class TestCommandsSendStdin:
    @respx.mock
    def test_send_stdin(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        route = respx.post(f"{API_URL}/sandboxes/sbx-cmd/commands/42/stdin").mock(
            return_value=httpx.Response(200, json={})
        )
        sandbox = _create_sandbox()
        sandbox.commands.send_stdin(42, "input data\n")
        req_body = json.loads(route.calls[0].request.content)
        assert req_body["data"] == "input data\n"


class TestCommandHandle:
    @respx.mock
    def test_wait_success(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-cmd/commands").mock(
            return_value=httpx.Response(200, json={"pid": 10})
        )
        respx.get(f"{API_URL}/sandboxes/sbx-cmd/commands/10/wait").mock(
            return_value=httpx.Response(
                200,
                json={
                    "stdout": "done\n",
                    "stderr": "",
                    "exit_code": 0,
                },
            )
        )
        sandbox = _create_sandbox()
        handle = sandbox.commands.run("long-cmd", background=True)
        result = handle.wait()
        assert result.stdout == "done\n"

    @respx.mock
    def test_wait_failure_raises(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-cmd/commands").mock(
            return_value=httpx.Response(200, json={"pid": 10})
        )
        respx.get(f"{API_URL}/sandboxes/sbx-cmd/commands/10/wait").mock(
            return_value=httpx.Response(
                200,
                json={
                    "stdout": "",
                    "stderr": "error\n",
                    "exit_code": 1,
                },
            )
        )
        sandbox = _create_sandbox()
        handle = sandbox.commands.run("fail-cmd", background=True)
        with pytest.raises(CommandExitException) as exc_info:
            handle.wait()
        assert exc_info.value.exit_code == 1
        assert exc_info.value.stderr == "error\n"
