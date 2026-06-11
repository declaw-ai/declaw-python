"""Integration tests: command execution against the mock backend."""


class TestCommandExecution:
    def test_run_echo(self, mock_client):
        resp = mock_client.post(
            "/sandboxes", json={"template": "base", "timeout": 60, "secure": True}
        )
        sbx_id = resp.json()["sandbox_id"]

        cmd_resp = mock_client.post(
            f"/sandboxes/{sbx_id}/commands",
            json={
                "cmd": "echo hello world",
                "background": False,
                "user": "user",
            },
        )
        data = cmd_resp.json()
        assert data["stdout"].strip() == "hello world"
        assert data["exit_code"] == 0

    def test_run_with_envs(self, mock_client):
        resp = mock_client.post(
            "/sandboxes",
            json={
                "template": "base",
                "timeout": 60,
                "secure": True,
                "envs": {"TEST_VAR": "from_sandbox"},
            },
        )
        sbx_id = resp.json()["sandbox_id"]

        cmd_resp = mock_client.post(
            f"/sandboxes/{sbx_id}/commands",
            json={
                "cmd": "echo $TEST_VAR",
                "background": False,
                "user": "user",
            },
        )
        assert cmd_resp.json()["stdout"].strip() == "from_sandbox"

    def test_run_with_per_command_envs(self, mock_client):
        resp = mock_client.post(
            "/sandboxes", json={"template": "base", "timeout": 60, "secure": True}
        )
        sbx_id = resp.json()["sandbox_id"]

        cmd_resp = mock_client.post(
            f"/sandboxes/{sbx_id}/commands",
            json={
                "cmd": "echo $CMD_VAR",
                "background": False,
                "user": "user",
                "envs": {"CMD_VAR": "per_command"},
            },
        )
        assert cmd_resp.json()["stdout"].strip() == "per_command"

    def test_run_declaw_env_vars_injected(self, mock_client):
        resp = mock_client.post(
            "/sandboxes", json={"template": "base", "timeout": 60, "secure": True}
        )
        sbx_id = resp.json()["sandbox_id"]

        cmd_resp = mock_client.post(
            f"/sandboxes/{sbx_id}/commands",
            json={
                "cmd": "echo $DECLAW_SANDBOX",
                "background": False,
                "user": "user",
            },
        )
        assert cmd_resp.json()["stdout"].strip() == "true"

    def test_run_background_and_wait(self, mock_client):
        resp = mock_client.post(
            "/sandboxes", json={"template": "base", "timeout": 60, "secure": True}
        )
        sbx_id = resp.json()["sandbox_id"]

        bg_resp = mock_client.post(
            f"/sandboxes/{sbx_id}/commands",
            json={
                "cmd": "echo background_result",
                "background": True,
                "user": "user",
            },
        )
        pid = bg_resp.json()["pid"]
        assert pid > 0

        wait_resp = mock_client.get(f"/sandboxes/{sbx_id}/commands/{pid}/wait")
        assert wait_resp.json()["stdout"].strip() == "background_result"
        assert wait_resp.json()["exit_code"] == 0

    def test_list_and_kill_commands(self, mock_client):
        resp = mock_client.post(
            "/sandboxes", json={"template": "base", "timeout": 60, "secure": True}
        )
        sbx_id = resp.json()["sandbox_id"]

        mock_client.post(
            f"/sandboxes/{sbx_id}/commands",
            json={
                "cmd": "sleep 100",
                "background": True,
                "user": "user",
            },
        )
        procs = mock_client.get(f"/sandboxes/{sbx_id}/commands").json()
        assert len(procs) >= 1

        pid = procs[0]["pid"]
        kill_resp = mock_client.delete(f"/sandboxes/{sbx_id}/commands/{pid}")
        assert kill_resp.json()["killed"] is True
