import json

import httpx
import pytest
import respx

from declaw import AsyncTemplate, BuildInfo, Template, TemplateBase, TemplateBuildStatus
from declaw.exceptions import (
    BuildError,
    InvalidArgumentError,
    NotFoundError,
    RateLimitException,
    TimeoutError,
)

API_URL = "https://api.test.dev"
BUILD_URL = f"{API_URL}/templates/build"
STATUS_URL = f"{API_URL}/templates/builds/bld-1"

# What sandbox-manager answers: starting a build returns 201 "building" with
# no logs; the logs only ever come from GET /templates/builds/:build_id.
SUBMITTED = {"build_id": "bld-1", "status": "building", "template_id": "tpl-1"}


def build_status(status, logs):
    return {"build_id": "bld-1", "status": status, "template_id": "tpl-1", "logs": logs}


@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    monkeypatch.setenv("DECLAW_API_KEY", "test-key")
    monkeypatch.setenv("DECLAW_DOMAIN", "api.test.dev")
    # Real builds are polled every few seconds; the tests only need the loop.
    monkeypatch.setattr("declaw.template.main.BUILD_POLL_INTERVAL", 0)


def mock_build(statuses):
    """Mock the two build endpoints; each status poll answers the next entry."""
    submit = respx.post(BUILD_URL).mock(return_value=httpx.Response(201, json=SUBMITTED))
    polls = respx.get(STATUS_URL).mock(side_effect=[httpx.Response(200, json=s) for s in statuses])
    return submit, polls


class TestTemplateBase:
    def test_builder_chain(self):
        t = (
            TemplateBase()
            .from_base_image("python:3.12")
            .apt_install("curl", "git")
            .run_cmd(["pip install numpy"])
            .set_envs({"APP_ENV": "production"})
            .set_start_cmd("python main.py")
        )
        # The server's field names, exactly: it silently ignores any other.
        assert t.to_dict() == {
            "base_image": "python:3.12",
            "packages": ["curl", "git"],
            "run_cmds": ["pip install numpy"],
            "envs": {"APP_ENV": "production"},
            "start_cmd": "python main.py",
        }

    def test_default_base_image(self):
        t = TemplateBase()
        assert t.to_dict()["base_image"] == "ubuntu:22.04"

    def test_multiple_run_cmds(self):
        t = TemplateBase().run_cmd(["apt update"]).run_cmd(["apt install -y curl"])
        assert len(t.to_dict()["run_cmds"]) == 2

    def test_dockerfile_sends_only_the_dockerfile(self):
        t = TemplateBase().apt_install("curl").from_dockerfile("FROM ubuntu:22.04\n")
        assert t.to_dict() == {"dockerfile": "FROM ubuntu:22.04\n"}


class TestTemplateBuild:
    @respx.mock
    def test_build_request_matches_server_contract(self):
        submit, _ = mock_build([build_status("completed", [])])
        t = TemplateBase().from_base_image("python:3.12").apt_install("ffmpeg")
        Template.build(t, "my-template", cpu_count=2, memory_mb=2048)
        assert json.loads(submit.calls[0].request.content) == {
            "template": {"base_image": "python:3.12", "packages": ["ffmpeg"]},
            "alias": "my-template",
            "cpu_count": 2,
            "memory_mb": 2048,
        }

    @respx.mock
    def test_build_waits_and_streams_each_log_line_once(self):
        _, polls = mock_build(
            [
                build_status("building", ["Step 1/3"]),
                build_status("building", ["Step 1/3", "Step 2/3"]),
                build_status("completed", ["Step 1/3", "Step 2/3", "Step 3/3"]),
            ]
        )
        logs = []
        info = Template.build(TemplateBase(), "my-template", on_build_logs=logs.append)
        assert logs == ["Step 1/3", "Step 2/3", "Step 3/3"]
        assert isinstance(info, BuildInfo)
        assert (info.build_id, info.status, info.template_id) == ("bld-1", "completed", "tpl-1")
        assert info.logs == ["Step 1/3", "Step 2/3", "Step 3/3"]
        assert polls.call_count == 3

    @respx.mock
    def test_failed_build_raises_build_error_with_its_logs(self):
        lines = [f"line {i:02d}" for i in range(1, 26)]
        mock_build([build_status("failed", lines)])
        with pytest.raises(BuildError) as exc:
            Template.build(TemplateBase(), "my-template")
        assert exc.value.build_id == "bld-1"
        assert exc.value.logs == lines
        message = str(exc.value)
        assert "line 25" in message and "line 06" in message
        assert "line 05" not in message  # only the last 20 lines are quoted

    @respx.mock
    def test_build_times_out_while_still_building(self):
        # A finite set of responses, so a missing deadline fails the test
        # instead of polling forever and hanging the suite.
        mock_build([build_status("building", [])] * 3)
        with pytest.raises(TimeoutError, match="bld-1"):
            Template.build(TemplateBase(), "my-template", build_timeout=0)

    @respx.mock
    def test_copy_is_rejected_before_any_request(self):
        submit = respx.post(BUILD_URL).mock(return_value=httpx.Response(201, json=SUBMITTED))
        t = TemplateBase().copy("config.json", "/app/config.json")
        with pytest.raises(InvalidArgumentError, match="copy"):
            Template.build(t, "my-template")
        with pytest.raises(InvalidArgumentError, match="copy"):
            Template.build_in_background(t, "my-template")
        assert submit.call_count == 0

    @respx.mock
    def test_build_with_disk_mb(self):
        submit, _ = mock_build([build_status("completed", [])])
        Template.build(TemplateBase(), "disk-template", disk_mb=2048)
        assert json.loads(submit.calls[0].request.content)["disk_mb"] == 2048

    @respx.mock
    def test_build_in_background_returns_without_polling(self):
        submit, polls = mock_build([build_status("completed", [])])
        info = Template.build_in_background(TemplateBase(), "bg-template", disk_mb=4096)
        assert (info.build_id, info.status) == ("bld-1", "building")
        assert polls.call_count == 0
        body = json.loads(submit.calls[0].request.content)
        assert body == {
            "template": {"base_image": "ubuntu:22.04"},
            "alias": "bg-template",
            "disk_mb": 4096,
        }

    @respx.mock
    def test_get_build_status(self):
        respx.get(STATUS_URL).mock(
            return_value=httpx.Response(200, json=build_status("completed", ["done"]))
        )
        status = Template.get_build_status("bld-1")
        assert isinstance(status, TemplateBuildStatus)
        assert (status.status, status.logs, status.template_id) == ("completed", ["done"], "tpl-1")

    @respx.mock
    def test_get_build_status_with_null_logs(self):
        # A build with no output yet serializes its logs as null.
        respx.get(STATUS_URL).mock(
            return_value=httpx.Response(200, json=build_status("building", None))
        )
        assert Template.get_build_status("bld-1").logs == []


class TestAsyncTemplateBuild:
    @respx.mock
    @pytest.mark.asyncio
    async def test_async_build_waits_and_streams_each_log_line_once(self):
        submit, polls = mock_build(
            [
                build_status("building", ["Step 1/2"]),
                build_status("completed", ["Step 1/2", "Step 2/2"]),
            ]
        )
        logs = []
        info = await AsyncTemplate.build(
            TemplateBase().apt_install("jq"), "async-tpl", disk_mb=2048, on_build_logs=logs.append
        )
        assert logs == ["Step 1/2", "Step 2/2"]
        assert (info.status, info.template_id) == ("completed", "tpl-1")
        assert polls.call_count == 2
        assert json.loads(submit.calls[0].request.content) == {
            "template": {"base_image": "ubuntu:22.04", "packages": ["jq"]},
            "alias": "async-tpl",
            "disk_mb": 2048,
        }

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_failed_build_raises_build_error(self):
        mock_build([build_status("failed", ["E: Unable to locate package nope"])])
        with pytest.raises(BuildError, match="Unable to locate package") as exc:
            await AsyncTemplate.build(TemplateBase(), "async-tpl")
        assert exc.value.build_id == "bld-1"

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_build_times_out_while_still_building(self):
        mock_build([build_status("building", [])] * 3)
        with pytest.raises(TimeoutError, match="bld-1"):
            await AsyncTemplate.build(TemplateBase(), "async-tpl", build_timeout=0)

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_copy_is_rejected_before_any_request(self):
        submit = respx.post(BUILD_URL).mock(return_value=httpx.Response(201, json=SUBMITTED))
        with pytest.raises(InvalidArgumentError, match="copy"):
            await AsyncTemplate.build(TemplateBase().copy("a", "/a"), "async-tpl")
        with pytest.raises(InvalidArgumentError, match="copy"):
            await AsyncTemplate.build_in_background(TemplateBase().copy("a", "/a"), "async-tpl")
        assert submit.call_count == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_build_in_background_returns_without_polling(self):
        submit, polls = mock_build([build_status("completed", [])])
        info = await AsyncTemplate.build_in_background(TemplateBase(), "bg-tpl", disk_mb=4096)
        assert (info.build_id, info.status) == ("bld-1", "building")
        assert polls.call_count == 0
        assert json.loads(submit.calls[0].request.content) == {
            "template": {"base_image": "ubuntu:22.04"},
            "alias": "bg-tpl",
            "disk_mb": 4096,
        }

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_get_build_status(self):
        respx.get(STATUS_URL).mock(
            return_value=httpx.Response(200, json=build_status("completed", []))
        )
        status = await AsyncTemplate.get_build_status("bld-1")
        assert status.status == "completed"


# --- Streaming past the server's log cap, and failed status checks ---------

NOTICE = "... [earlier build output truncated]"


def stored_logs(total):
    """What sandbox-manager returns for a build that has produced ``total`` lines:
    past its 2000-line cap, the truncation notice plus the newest 1999."""
    lines = [f"line {i}" for i in range(1, total + 1)]
    return lines if total <= 2000 else [NOTICE] + lines[-1999:]


def statuses_through(totals):
    last = len(totals) - 1
    return [
        build_status("completed" if i == last else "building", stored_logs(t))
        for i, t in enumerate(totals)
    ]


class TestLogCursor:
    def test_hands_out_each_line_once_across_the_cap(self):
        from declaw.template.main import _LogCursor

        lines = lambda a, b: [f"line {i}" for i in range(a, b + 1)]  # noqa: E731
        c = _LogCursor()
        assert c.new_lines(stored_logs(1980)) == lines(1, 1980)
        assert c.new_lines(stored_logs(1980)) == []
        assert c.new_lines(stored_logs(2050)) == lines(1981, 2050)
        assert c.new_lines(stored_logs(2600)) == lines(2051, 2600)
        # More output than the server keeps arrived between two polls: the
        # notice marks the gap before what remains.
        assert c.new_lines(stored_logs(9000)) == stored_logs(9000)

    def test_following_a_build_already_past_the_cap_starts_at_the_notice(self):
        from declaw.template.main import _LogCursor

        assert _LogCursor().new_lines(stored_logs(2500)) == stored_logs(2500)


class TestBuildWaitRobustness:
    @respx.mock
    def test_streams_each_line_once_across_the_log_cap(self):
        mock_build(statuses_through([1980, 2050, 2600, 3000]))
        got = []
        info = Template.build(TemplateBase(), "big", on_build_logs=got.append)
        assert got == [f"line {i}" for i in range(1, 3001)]
        assert info.status == "completed"

    @respx.mock
    def test_rides_out_temporary_failures(self):
        respx.post(BUILD_URL).mock(return_value=httpx.Response(201, json=SUBMITTED))
        polls = respx.get(STATUS_URL).mock(
            side_effect=[
                httpx.RemoteProtocolError("Server disconnected without sending a response."),
                httpx.Response(429, json={"message": "slow down"}),
                httpx.Response(200, json=build_status("completed", ["done"])),
            ]
        )
        info = Template.build(TemplateBase(), "flaky")
        assert info.status == "completed"
        assert polls.call_count == 3

    @respx.mock
    def test_gives_up_after_the_error_window(self, monkeypatch):
        monkeypatch.setattr("declaw.template.main.BUILD_POLL_ERROR_WINDOW", 0)
        respx.post(BUILD_URL).mock(return_value=httpx.Response(201, json=SUBMITTED))
        # Finite, so a wait that never gives up fails here instead of hanging.
        respx.get(STATUS_URL).mock(
            side_effect=[httpx.Response(429, json={"message": "slow down"})] * 5
        )
        with pytest.raises(RateLimitException):
            Template.build(TemplateBase(), "flaky")

    @respx.mock
    def test_a_rejection_ends_the_wait(self, monkeypatch):
        # A short window, so a rejection wrongly treated as temporary shows up
        # as extra polls rather than a two-minute test.
        monkeypatch.setattr("declaw.template.main.BUILD_POLL_ERROR_WINDOW", 0.2)
        respx.post(BUILD_URL).mock(return_value=httpx.Response(201, json=SUBMITTED))
        polls = respx.get(STATUS_URL).mock(
            return_value=httpx.Response(404, json={"message": "build bld-1 not found"})
        )
        with pytest.raises(NotFoundError):
            Template.build(TemplateBase(), "gone")
        assert polls.call_count == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_streams_across_the_cap_and_rides_out_failures(self):
        respx.post(BUILD_URL).mock(return_value=httpx.Response(201, json=SUBMITTED))
        responses = [httpx.Response(200, json=s) for s in statuses_through([1980, 2600, 3000])]
        respx.get(STATUS_URL).mock(
            side_effect=[responses[0], httpx.RemoteProtocolError("reset"), *responses[1:]]
        )
        got = []
        info = await AsyncTemplate.build(TemplateBase(), "big", on_build_logs=got.append)
        assert got == [f"line {i}" for i in range(1, 3001)]
        assert info.status == "completed"

    def test_a_successful_check_resets_the_error_window(self, monkeypatch):
        from declaw.template.main import BuildInfo as _Info
        from declaw.template.main import TemplateBuildStatus as _Status
        from declaw.template.main import _BuildWatcher

        now = [0.0]
        monkeypatch.setattr("declaw.template.main.time.monotonic", lambda: now[0])
        monkeypatch.setattr("declaw.template.main.BUILD_POLL_ERROR_WINDOW", 10)
        watcher = _BuildWatcher(_Info("bld-1", "building"), 3600, None)
        blip = RateLimitException("HTTP 429: slow down")

        watcher.poll_failed(blip)  # t=0: a failure streak starts
        now[0] = 5.0
        assert watcher.observe(_Status("bld-1", "building")) is None  # t=5: it ends
        now[0] = 12.0
        watcher.poll_failed(blip)  # t=12: a new streak, not 12s into the old one
        now[0] = 23.0
        with pytest.raises(RateLimitException):
            watcher.poll_failed(blip)  # t=23: 11s into the new streak

    def test_the_deadline_applies_while_status_checks_fail(self, monkeypatch):
        from declaw.template.main import BuildInfo as _Info
        from declaw.template.main import _BuildWatcher

        now = [0.0]
        monkeypatch.setattr("declaw.template.main.time.monotonic", lambda: now[0])
        monkeypatch.setattr("declaw.template.main.BUILD_POLL_ERROR_WINDOW", 100)
        watcher = _BuildWatcher(_Info("bld-1", "building"), 10, None)
        blip = RateLimitException("HTTP 429: slow down")

        watcher.poll_failed(blip)  # t=0: within both the window and the deadline
        now[0] = 11.0
        with pytest.raises(TimeoutError, match="bld-1"):
            watcher.poll_failed(blip)  # t=11: past the 10s deadline, inside the window
