import json

import httpx
import pytest
import respx

from declaw import AsyncTemplate, BuildInfo, Template, TemplateBase, TemplateBuildStatus

API_URL = "https://api.test.dev"


@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    monkeypatch.setenv("DECLAW_API_KEY", "test-key")
    monkeypatch.setenv("DECLAW_DOMAIN", "api.test.dev")


class TestTemplateBase:
    def test_builder_chain(self):
        t = (
            TemplateBase()
            .from_base_image("python:3.12")
            .apt_install("curl", "git")
            .run_cmd(["pip install numpy"])
            .copy("config.json", "/app/config.json")
            .set_envs({"APP_ENV": "production"})
            .set_start_cmd("python main.py")
        )
        d = t.to_dict()
        assert d["base_image"] == "python:3.12"
        assert d["apt_packages"] == ["curl", "git"]
        assert "pip install numpy" in d["run_cmds"]
        assert len(d["copies"]) == 1
        assert d["copies"][0]["src"] == "config.json"
        assert d["envs"]["APP_ENV"] == "production"
        assert d["start_cmd"] == "python main.py"

    def test_default_base_image(self):
        t = TemplateBase()
        assert t.to_dict()["base_image"] == "ubuntu:22.04"

    def test_multiple_run_cmds(self):
        t = TemplateBase().run_cmd(["apt update"]).run_cmd(["apt install -y curl"])
        assert len(t.to_dict()["run_cmds"]) == 2

    def test_copy_with_mode(self):
        t = TemplateBase().copy("script.sh", "/run.sh", mode=0o755)
        copies = t.to_dict()["copies"]
        assert copies[0]["mode"] == 0o755


class TestTemplateBuild:
    @respx.mock
    def test_build(self):
        route = respx.post(f"{API_URL}/templates/build").mock(
            return_value=httpx.Response(
                200,
                json={
                    "build_id": "build-1",
                    "status": "completed",
                    "template_id": "tpl-custom",
                    "logs": ["Step 1/3: FROM python:3.12", "Step 2/3: RUN pip install numpy"],
                },
            )
        )
        t = TemplateBase().from_base_image("python:3.12")
        logs_collected = []
        info = Template.build(
            t,
            "my-template",
            cpu_count=2,
            memory_mb=2048,
            on_build_logs=lambda log: logs_collected.append(log),
            api_key="test-key",
            domain="api.test.dev",
        )
        assert isinstance(info, BuildInfo)
        assert info.build_id == "build-1"
        assert info.status == "completed"
        assert len(logs_collected) == 2
        body = json.loads(route.calls[0].request.content)
        assert body["alias"] == "my-template"
        assert body["cpu_count"] == 2
        assert body["memory_mb"] == 2048
        assert "disk_mb" not in body  # omitted when not set; backend applies default

    @respx.mock
    def test_build_in_background(self):
        respx.post(f"{API_URL}/templates/build").mock(
            return_value=httpx.Response(
                200,
                json={
                    "build_id": "build-2",
                    "status": "building",
                },
            )
        )
        t = TemplateBase().from_base_image()
        info = Template.build_in_background(
            t, "bg-template", api_key="test-key", domain="api.test.dev"
        )
        assert info.status == "building"

    @respx.mock
    def test_build_with_disk_mb(self):
        route = respx.post(f"{API_URL}/templates/build").mock(
            return_value=httpx.Response(
                200,
                json={
                    "build_id": "build-disk",
                    "status": "completed",
                    "template_id": "tpl-disk",
                },
            )
        )
        t = TemplateBase().from_base_image("ubuntu:22.04")
        info = Template.build(
            t,
            "disk-template",
            disk_mb=2048,
            api_key="test-key",
            domain="api.test.dev",
        )
        assert isinstance(info, BuildInfo)
        body = json.loads(route.calls[0].request.content)
        assert body["disk_mb"] == 2048

    @respx.mock
    def test_build_in_background_with_disk_mb(self):
        route = respx.post(f"{API_URL}/templates/build").mock(
            return_value=httpx.Response(
                200,
                json={
                    "build_id": "build-bg-disk",
                    "status": "building",
                },
            )
        )
        t = TemplateBase().from_base_image()
        Template.build_in_background(
            t, "bg-disk-template", disk_mb=4096, api_key="test-key", domain="api.test.dev"
        )
        body = json.loads(route.calls[0].request.content)
        assert body["disk_mb"] == 4096
        assert body["background"] is True

    @respx.mock
    def test_get_build_status(self):
        respx.get(f"{API_URL}/templates/builds/build-2").mock(
            return_value=httpx.Response(
                200,
                json={
                    "build_id": "build-2",
                    "status": "completed",
                    "logs": ["done"],
                },
            )
        )
        status = Template.get_build_status("build-2", api_key="test-key", domain="api.test.dev")
        assert isinstance(status, TemplateBuildStatus)
        assert status.status == "completed"
        assert status.logs == ["done"]


class TestAsyncTemplateBuild:
    @respx.mock
    @pytest.mark.asyncio
    async def test_async_build(self):
        respx.post(f"{API_URL}/templates/build").mock(
            return_value=httpx.Response(
                200,
                json={
                    "build_id": "build-3",
                    "status": "completed",
                    "template_id": "tpl-async",
                },
            )
        )
        t = TemplateBase().from_base_image("node:20")
        info = await AsyncTemplate.build(t, "async-tpl", api_key="test-key", domain="api.test.dev")
        assert info.build_id == "build-3"

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_build_with_disk_mb(self):
        route = respx.post(f"{API_URL}/templates/build").mock(
            return_value=httpx.Response(
                200,
                json={
                    "build_id": "build-async-disk",
                    "status": "completed",
                    "template_id": "tpl-async-disk",
                },
            )
        )
        t = TemplateBase().from_base_image("python:3.12")
        info = await AsyncTemplate.build(
            t, "async-disk-tpl", disk_mb=2048, api_key="test-key", domain="api.test.dev"
        )
        assert info.build_id == "build-async-disk"
        body = json.loads(route.calls[0].request.content)
        assert body["disk_mb"] == 2048

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_get_build_status(self):
        respx.get(f"{API_URL}/templates/builds/build-3").mock(
            return_value=httpx.Response(
                200,
                json={
                    "build_id": "build-3",
                    "status": "completed",
                    "logs": [],
                },
            )
        )
        status = await AsyncTemplate.get_build_status(
            "build-3", api_key="test-key", domain="api.test.dev"
        )
        assert status.status == "completed"
