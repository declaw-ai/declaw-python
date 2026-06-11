"""Integration tests: Sandbox lifecycle against the mock backend."""

from declaw.sandbox.network import ALL_TRAFFIC
from declaw.security.pii import PIIConfig
from declaw.security.policy import SecurityPolicy


class TestSandboxCreateAndKill:
    def test_create_basic(self, mock_client, mock_config):
        resp = mock_client.post(
            "/sandboxes", json={"template": "base", "timeout": 300, "secure": True}
        )
        data = resp.json()
        assert "sandbox_id" in data
        assert data["state"] == "running"

        sbx_id = data["sandbox_id"]
        resp2 = mock_client.get(f"/sandboxes/{sbx_id}")
        assert resp2.json()["sandbox_id"] == sbx_id

    def test_create_with_envs(self, mock_client):
        resp = mock_client.post(
            "/sandboxes",
            json={
                "template": "base",
                "timeout": 60,
                "secure": True,
                "envs": {"MY_VAR": "hello"},
            },
        )
        data = resp.json()
        assert data["envs"]["MY_VAR"] == "hello"

    def test_create_with_network_deny_all(self, mock_client):
        resp = mock_client.post(
            "/sandboxes",
            json={
                "template": "base",
                "timeout": 60,
                "secure": True,
                "network": {"deny_out": [ALL_TRAFFIC]},
            },
        )
        data = resp.json()
        assert data["network"]["deny_out"] == [ALL_TRAFFIC]

    def test_create_with_domain_allowlist(self, mock_client):
        resp = mock_client.post(
            "/sandboxes",
            json={
                "template": "base",
                "timeout": 60,
                "secure": True,
                "network": {"allow_out": ["*.openai.com"], "deny_out": [ALL_TRAFFIC]},
            },
        )
        data = resp.json()
        assert "*.openai.com" in data["network"]["allow_out"]

    def test_create_with_security_policy(self, mock_client):
        policy = SecurityPolicy(
            pii=PIIConfig(enabled=True, types=["ssn", "email"]),
            audit=True,
        )
        resp = mock_client.post(
            "/sandboxes",
            json={
                "template": "base",
                "timeout": 60,
                "secure": True,
                "security": policy.to_dict(),
            },
        )
        data = resp.json()
        assert data["security"]["pii"]["enabled"] is True

    def test_kill(self, mock_client):
        resp = mock_client.post(
            "/sandboxes", json={"template": "base", "timeout": 60, "secure": True}
        )
        sbx_id = resp.json()["sandbox_id"]

        kill_resp = mock_client.delete(f"/sandboxes/{sbx_id}")
        assert kill_resp.json()["killed"] is True

        status_resp = mock_client.get(f"/sandboxes/{sbx_id}/status")
        assert status_resp.json()["is_running"] is False

    def test_set_timeout(self, mock_client):
        resp = mock_client.post(
            "/sandboxes", json={"template": "base", "timeout": 60, "secure": True}
        )
        sbx_id = resp.json()["sandbox_id"]
        mock_client.patch(f"/sandboxes/{sbx_id}/timeout", json={"timeout": 120})
        info = mock_client.get(f"/sandboxes/{sbx_id}").json()
        assert info["timeout"] == 120

    def test_get_metrics(self, mock_client):
        resp = mock_client.post(
            "/sandboxes", json={"template": "base", "timeout": 60, "secure": True}
        )
        sbx_id = resp.json()["sandbox_id"]
        metrics = mock_client.get(f"/sandboxes/{sbx_id}/metrics").json()
        assert len(metrics) == 1
        assert "cpu_usage_percent" in metrics[0]

    def test_pause_and_connect(self, mock_client):
        resp = mock_client.post(
            "/sandboxes", json={"template": "base", "timeout": 60, "secure": True}
        )
        sbx_id = resp.json()["sandbox_id"]

        mock_client.post(f"/sandboxes/{sbx_id}/pause")
        status = mock_client.get(f"/sandboxes/{sbx_id}").json()
        assert status["state"] == "paused"

        connect = mock_client.get(f"/sandboxes/{sbx_id}").json()
        assert connect["sandbox_id"] == sbx_id
