import httpx
import pytest
import respx

from declaw import AsyncSandbox, CommandResult, PIIConfig, SandboxInfo, SecurityPolicy
from declaw.exceptions import CommandExitException
from declaw.sandbox_async.commands.command_handle import AsyncCommandHandle

API_URL = "https://api.test.dev"
SANDBOX_RESP = {
    "sandbox_id": "sbx-async-1",
    "template_id": "tpl-base",
    "name": "base",
    "envd_access_token": "tok-1",
    "sandbox_domain": "test.dev",
    "traffic_access_token": "traffic-tok",
    "state": "running",
    "metadata": {},
    "started_at": "2026-01-01T00:00:00",
}


@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    monkeypatch.setenv("DECLAW_API_KEY", "test-key")
    monkeypatch.setenv("DECLAW_DOMAIN", "api.test.dev")


class TestAsyncSandboxCreate:
    @respx.mock
    @pytest.mark.asyncio
    async def test_create(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        assert sandbox.sandbox_id == "sbx-async-1"
        assert sandbox.traffic_access_token == "traffic-tok"

    @respx.mock
    @pytest.mark.asyncio
    async def test_create_with_security(self):
        route = respx.post(f"{API_URL}/sandboxes").mock(
            return_value=httpx.Response(201, json=SANDBOX_RESP)
        )
        policy = SecurityPolicy(pii=PIIConfig(enabled=True, types=["ssn"]), audit=True)
        await AsyncSandbox.create(security=policy, api_key="test-key", domain="api.test.dev")
        import json

        body = json.loads(route.calls[0].request.content)
        policy_dict = json.loads(body["security"]["policy_json"])
        assert policy_dict["pii"]["enabled"] is True


class TestAsyncSandboxConnect:
    @respx.mock
    @pytest.mark.asyncio
    async def test_connect(self):
        respx.get(f"{API_URL}/sandboxes/sbx-async-1").mock(
            return_value=httpx.Response(200, json=SANDBOX_RESP)
        )
        sandbox = await AsyncSandbox.connect(
            "sbx-async-1", api_key="test-key", domain="api.test.dev"
        )
        assert sandbox.sandbox_id == "sbx-async-1"


class TestAsyncSandboxLifecycle:
    @respx.mock
    @pytest.mark.asyncio
    async def test_kill(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.delete(f"{API_URL}/sandboxes/sbx-async-1").mock(
            return_value=httpx.Response(200, json={"killed": True})
        )
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        assert await sandbox.kill() is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_is_running(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.get(f"{API_URL}/sandboxes/sbx-async-1/status").mock(
            return_value=httpx.Response(200, json={"is_running": True})
        )
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        assert await sandbox.is_running() is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_set_timeout(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.patch(f"{API_URL}/sandboxes/sbx-async-1/timeout").mock(
            return_value=httpx.Response(200, json={})
        )
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        await sandbox.set_timeout(120)

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_info(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.get(f"{API_URL}/sandboxes/sbx-async-1").mock(
            return_value=httpx.Response(200, json=SANDBOX_RESP)
        )
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        info = await sandbox.get_info()
        assert isinstance(info, SandboxInfo)

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_host(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        assert sandbox.get_host(8080) == f"{API_URL}:443/sandboxes/sbx-async-1/ports/8080"

    @respx.mock
    @pytest.mark.asyncio
    async def test_download_url(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        expected = f"{API_URL}:443/sandboxes/sbx-async-1/files/raw?path=%2Fp"
        assert sandbox.download_url("/p") == expected


class TestAsyncCommands:
    @respx.mock
    @pytest.mark.asyncio
    async def test_run_foreground(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-async-1/commands").mock(
            return_value=httpx.Response(200, json={"stdout": "hi\n", "stderr": "", "exit_code": 0})
        )
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        result = await sandbox.run_command("echo hi")
        assert isinstance(result, CommandResult)
        assert result.stdout == "hi\n"

    @respx.mock
    @pytest.mark.asyncio
    async def test_run_background(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-async-1/commands").mock(
            return_value=httpx.Response(200, json={"pid": 55})
        )
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        handle = await sandbox.run_command("sleep 10", background=True)
        assert isinstance(handle, AsyncCommandHandle)
        assert handle.pid == 55

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_handle_wait(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-async-1/commands").mock(
            return_value=httpx.Response(200, json={"pid": 55})
        )
        respx.get(f"{API_URL}/sandboxes/sbx-async-1/commands/55/wait").mock(
            return_value=httpx.Response(
                200, json={"stdout": "done\n", "stderr": "", "exit_code": 0}
            )
        )
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        handle = await sandbox.run_command("cmd", background=True)
        result = await handle.wait()
        assert result.stdout == "done\n"

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_handle_wait_failure(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-async-1/commands").mock(
            return_value=httpx.Response(200, json={"pid": 55})
        )
        respx.get(f"{API_URL}/sandboxes/sbx-async-1/commands/55/wait").mock(
            return_value=httpx.Response(
                200, json={"stdout": "", "stderr": "fail\n", "exit_code": 2}
            )
        )
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        handle = await sandbox.run_command("cmd", background=True)
        with pytest.raises(CommandExitException):
            await handle.wait()


class TestAsyncFilesystem:
    @respx.mock
    @pytest.mark.asyncio
    async def test_read_file(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.get(f"{API_URL}/sandboxes/sbx-async-1/files").mock(
            return_value=httpx.Response(200, text="content")
        )
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        content = await sandbox.read_file("/test.txt")
        assert content == "content"

    @respx.mock
    @pytest.mark.asyncio
    async def test_write_file(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-async-1/files").mock(
            return_value=httpx.Response(200, json={"path": "/out.txt", "size": 5})
        )
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        info = await sandbox.write_file("/out.txt", "hello")
        assert info.path == "/out.txt"

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_files(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.get(f"{API_URL}/sandboxes/sbx-async-1/files/list").mock(
            return_value=httpx.Response(
                200, json=[{"name": "a.txt", "path": "/a.txt", "type": "file", "size": 10}]
            )
        )
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        entries = await sandbox.list_files("/")
        assert len(entries) == 1


class TestAsyncFilesystemBinary:
    """Pin async binary-write round-trip. Pre-fix these fail with U+FFFD corruption."""

    PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
    NON_UTF8 = bytes([0xFF, 0xFE, 0x00, 0x01, 0x80, 0x81, 0xC0, 0xC1])

    def test_async_client_has_put_method(self):
        """Guards the new AsyncApiClient.put() method this change depends on."""
        from declaw.api.async_client import AsyncApiClient

        assert hasattr(AsyncApiClient, "put")
        assert callable(getattr(AsyncApiClient, "put"))

    @respx.mock
    @pytest.mark.asyncio
    async def test_write_bytes_goes_to_raw_endpoint(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        raw_route = respx.put(f"{API_URL}/sandboxes/sbx-async-1/files/raw").mock(
            return_value=httpx.Response(200, json={"path": "/img.png", "size": len(self.PNG_MAGIC)})
        )
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        info = await sandbox.write_file("/img.png", self.PNG_MAGIC)
        assert raw_route.called, "bytes payload must be sent to PUT /files/raw"
        assert raw_route.calls[0].request.content == self.PNG_MAGIC
        assert info.size == len(self.PNG_MAGIC)

    @respx.mock
    @pytest.mark.asyncio
    async def test_write_bytes_non_utf8_byte_identical(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        raw_route = respx.put(f"{API_URL}/sandboxes/sbx-async-1/files/raw").mock(
            return_value=httpx.Response(200, json={"path": "/x.bin", "size": len(self.NON_UTF8)})
        )
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        await sandbox.write_file("/x.bin", self.NON_UTF8)
        assert raw_route.calls[0].request.content == self.NON_UTF8

    @respx.mock
    @pytest.mark.asyncio
    async def test_write_bytes_no_ffdb_fingerprint(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        raw_route = respx.put(f"{API_URL}/sandboxes/sbx-async-1/files/raw").mock(
            return_value=httpx.Response(200, json={"path": "/x.bin", "size": 2})
        )
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        await sandbox.write_file("/x.bin", b"\xff\xfe")
        body = raw_route.calls[0].request.content
        assert b"\xef\xbf\xbd" not in body
        assert body == b"\xff\xfe"

    @respx.mock
    @pytest.mark.asyncio
    async def test_write_str_still_uses_json_endpoint(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        json_route = respx.post(f"{API_URL}/sandboxes/sbx-async-1/files").mock(
            return_value=httpx.Response(200, json={"path": "/t.txt", "size": 5})
        )
        raw_route = respx.put(f"{API_URL}/sandboxes/sbx-async-1/files/raw").mock(
            return_value=httpx.Response(200, json={"path": "/t.txt", "size": 5})
        )
        sandbox = await AsyncSandbox.create(api_key="test-key", domain="api.test.dev")
        await sandbox.write_file("/t.txt", "hello")
        assert json_route.called
        assert not raw_route.called
