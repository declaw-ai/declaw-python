import httpx
import pytest
import respx

from declaw import ApiClient, ConnectionConfig
from declaw.exceptions import (
    AuthenticationException,
    NotFoundException,
    SandboxException,
    TimeoutException,
)


@pytest.fixture
def config():
    return ConnectionConfig(api_key="test-key", api_url="https://api.test.dev")


@pytest.fixture
def client(config):
    return ApiClient(config, max_retries=1)


class TestApiClient:
    @respx.mock
    def test_get_success(self, client):
        respx.get("https://api.test.dev/sandboxes").mock(
            return_value=httpx.Response(200, json={"sandboxes": []})
        )
        resp = client.get("/sandboxes")
        assert resp.status_code == 200
        assert resp.json() == {"sandboxes": []}

    @respx.mock
    def test_post_with_json(self, client):
        respx.post("https://api.test.dev/sandboxes").mock(
            return_value=httpx.Response(201, json={"sandbox_id": "sbx-1"})
        )
        resp = client.post("/sandboxes", json={"template": "base"})
        assert resp.json()["sandbox_id"] == "sbx-1"

    @respx.mock
    def test_auth_header_sent(self, client):
        route = respx.get("https://api.test.dev/test").mock(
            return_value=httpx.Response(200, json={})
        )
        client.get("/test")
        assert route.calls[0].request.headers["authorization"] == "Bearer test-key"

    @respx.mock
    def test_401_raises_auth_exception(self, client):
        respx.get("https://api.test.dev/test").mock(
            return_value=httpx.Response(401, json={"message": "unauthorized"})
        )
        with pytest.raises(AuthenticationException, match="401"):
            client.get("/test")

    @respx.mock
    def test_404_raises_not_found(self, client):
        respx.get("https://api.test.dev/sandboxes/missing").mock(
            return_value=httpx.Response(404, json={"message": "not found"})
        )
        with pytest.raises(NotFoundException, match="404"):
            client.get("/sandboxes/missing")

    @respx.mock
    def test_408_raises_timeout(self, client):
        respx.get("https://api.test.dev/slow").mock(
            return_value=httpx.Response(408, json={"message": "timeout"})
        )
        with pytest.raises(TimeoutException, match="408"):
            client.get("/slow")

    @respx.mock
    def test_500_raises_sandbox_exception(self, client):
        respx.get("https://api.test.dev/error").mock(
            return_value=httpx.Response(500, text="internal error")
        )
        with pytest.raises(SandboxException, match="500"):
            client.get("/error")

    @respx.mock
    def test_delete(self, client):
        respx.delete("https://api.test.dev/sandboxes/sbx-1").mock(
            return_value=httpx.Response(200, json={"killed": True})
        )
        resp = client.delete("/sandboxes/sbx-1")
        assert resp.json()["killed"] is True

    @respx.mock
    def test_patch(self, client):
        respx.patch("https://api.test.dev/sandboxes/sbx-1/timeout").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        resp = client.patch("/sandboxes/sbx-1/timeout", json={"timeout": 30})
        assert resp.json()["ok"] is True
