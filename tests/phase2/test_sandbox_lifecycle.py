import httpx
import pytest
import respx

from declaw import (
    ALL_TRAFFIC,
    PIIConfig,
    Sandbox,
    SandboxInfo,
    SecurityPolicy,
)
from declaw.sandbox.models import SandboxState

API_URL = "https://api.test.dev"

SANDBOX_RESP = {
    "sandbox_id": "sbx-123",
    "template_id": "tpl-base",
    "name": "base",
    "envd_access_token": "tok-1",
    "sandbox_domain": "test.dev",
    "traffic_access_token": "traffic-tok-1",
    "state": "running",
    "metadata": {},
    "started_at": "2026-01-01T00:00:00",
}


@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    monkeypatch.setenv("DECLAW_API_KEY", "test-key")
    monkeypatch.setenv("DECLAW_DOMAIN", "api.test.dev")


class TestSandboxCreate:
    @respx.mock
    def test_basic_create(self):
        route = respx.post(f"{API_URL}/sandboxes").mock(
            return_value=httpx.Response(201, json=SANDBOX_RESP)
        )
        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        assert sandbox.sandbox_id == "sbx-123"
        assert sandbox.traffic_access_token == "traffic-tok-1"

        body = route.calls[0].request.content
        import json

        req_body = json.loads(body)
        assert req_body["template"] == "base"
        assert req_body["timeout"] == 300

    @respx.mock
    def test_create_with_envs(self):
        route = respx.post(f"{API_URL}/sandboxes").mock(
            return_value=httpx.Response(201, json=SANDBOX_RESP)
        )
        Sandbox.create(
            envs={"MY_VAR": "hello"},
            api_key="test-key",
            domain="api.test.dev",
        )
        import json

        req_body = json.loads(route.calls[0].request.content)
        assert req_body["envs"] == {"MY_VAR": "hello"}

    @respx.mock
    def test_create_no_internet(self):
        route = respx.post(f"{API_URL}/sandboxes").mock(
            return_value=httpx.Response(201, json=SANDBOX_RESP)
        )
        Sandbox.create(
            allow_internet_access=False,
            api_key="test-key",
            domain="api.test.dev",
        )
        import json

        req_body = json.loads(route.calls[0].request.content)
        assert req_body["network"]["deny_out"] == [ALL_TRAFFIC]

    @respx.mock
    def test_create_with_domain_allowlist(self):
        route = respx.post(f"{API_URL}/sandboxes").mock(
            return_value=httpx.Response(201, json=SANDBOX_RESP)
        )
        Sandbox.create(
            network={
                "allow_out": ["*.openai.com", "*.anthropic.com"],
                "deny_out": [ALL_TRAFFIC],
            },
            api_key="test-key",
            domain="api.test.dev",
        )
        import json

        req_body = json.loads(route.calls[0].request.content)
        assert "*.openai.com" in req_body["network"]["allow_out"]
        assert ALL_TRAFFIC in req_body["network"]["deny_out"]

    @respx.mock
    def test_create_with_security_policy(self):
        route = respx.post(f"{API_URL}/sandboxes").mock(
            return_value=httpx.Response(201, json=SANDBOX_RESP)
        )
        policy = SecurityPolicy(
            pii=PIIConfig(enabled=True, types=["ssn", "email"]),
            audit=True,
        )
        Sandbox.create(
            security=policy,
            api_key="test-key",
            domain="api.test.dev",
        )
        import json

        req_body = json.loads(route.calls[0].request.content)
        policy_dict = json.loads(req_body["security"]["policy_json"])
        assert policy_dict["pii"]["enabled"] is True
        assert "ssn" in policy_dict["pii"]["types"]


class TestSandboxConnect:
    @respx.mock
    def test_connect(self):
        respx.get(f"{API_URL}/sandboxes/sbx-123").mock(
            return_value=httpx.Response(200, json=SANDBOX_RESP)
        )
        sandbox = Sandbox.connect("sbx-123", api_key="test-key", domain="api.test.dev")
        assert sandbox.sandbox_id == "sbx-123"


class TestSandboxLifecycle:
    @respx.mock
    def test_kill(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.delete(f"{API_URL}/sandboxes/sbx-123").mock(
            return_value=httpx.Response(200, json={"killed": True})
        )
        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        assert sandbox.kill() is True

    @respx.mock
    def test_is_running(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.get(f"{API_URL}/sandboxes/sbx-123/status").mock(
            return_value=httpx.Response(200, json={"is_running": True})
        )
        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        assert sandbox.is_running() is True

    @respx.mock
    def test_set_timeout(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        route = respx.patch(f"{API_URL}/sandboxes/sbx-123/timeout").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        sandbox.set_timeout(60)
        import json

        assert json.loads(route.calls[0].request.content)["timeout"] == 60

    @respx.mock
    def test_get_info(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.get(f"{API_URL}/sandboxes/sbx-123").mock(
            return_value=httpx.Response(200, json=SANDBOX_RESP)
        )
        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        info = sandbox.get_info()
        assert isinstance(info, SandboxInfo)
        assert info.sandbox_id == "sbx-123"
        assert info.state == SandboxState.RUNNING

    @respx.mock
    def test_get_metrics(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.get(f"{API_URL}/sandboxes/sbx-123/metrics").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "timestamp": "2026-01-01T12:00:00",
                        "cpu_usage_percent": 25.0,
                        "memory_usage_mb": 256.0,
                        "disk_usage_mb": 100.0,
                    }
                ],
            )
        )
        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        metrics = sandbox.get_metrics()
        assert len(metrics) == 1
        assert metrics[0].cpu_usage_percent == 25.0


class TestSandboxURLHelpers:
    """All URL helpers must return path-based URLs under `api.declaw.ai`,
    NEVER subdomain-style `<id>.api.declaw.ai`."""

    _BASE = f"{API_URL}:443/sandboxes/sbx-123"

    @respx.mock
    def test_envd_api_url(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        assert sandbox.envd_api_url == self._BASE

    @respx.mock
    def test_get_host(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        assert sandbox.get_host(3000) == f"{self._BASE}/ports/3000"

    @respx.mock
    def test_get_mcp_url(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        assert sandbox.get_mcp_url() == f"{self._BASE}/ports/50005/mcp"

    @respx.mock
    def test_download_url(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        url = sandbox.download_url("/home/user/file.txt")
        assert url == f"{self._BASE}/files/raw?path=%2Fhome%2Fuser%2Ffile.txt"

    @respx.mock
    def test_download_url_with_user(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        url = sandbox.download_url("/p", user="root")
        assert url == f"{self._BASE}/files/raw?path=%2Fp&username=root"

    @respx.mock
    def test_upload_url(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        url = sandbox.upload_url("/dest/file.txt", user="root")
        assert url == f"{self._BASE}/files/raw?path=%2Fdest%2Ffile.txt&username=root"

    @respx.mock
    def test_urls_never_contain_sandbox_subdomain(self):
        """Guard against accidentally reintroducing `<id>.domain` format."""
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        sandbox = Sandbox.create(api_key="test-key", domain="api.test.dev")
        for url in [
            sandbox.envd_api_url,
            sandbox.get_host(8080),
            sandbox.get_mcp_url(),
            sandbox.download_url("/x"),
            sandbox.upload_url("/x"),
        ]:
            assert "sbx-123." not in url, f"subdomain form leaked: {url}"
