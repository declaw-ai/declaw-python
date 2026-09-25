from __future__ import annotations

import time
from typing import Callable, Optional

from declaw.api.client import ApiClient, get_shared_client
from declaw.connection_config import ConnectionConfig
from declaw.exceptions import InvalidArgumentError
from declaw.template.main import (
    DEFAULT_BUILD_TIMEOUT,
    BuildInfo,
    TemplateBase,
    TemplateBuildStatus,
    _BuildWatcher,
    build_request_body,
)


class Template:
    """Sync template builder and manager."""

    @staticmethod
    def build(
        template: TemplateBase,
        alias: str,
        cpu_count: Optional[int] = None,
        memory_mb: Optional[int] = None,
        disk_mb: Optional[int] = None,
        on_build_logs: Optional[Callable[[str], None]] = None,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
        build_timeout: float = DEFAULT_BUILD_TIMEOUT,
    ) -> BuildInfo:
        """Build a template and wait for the build to finish.

        Builds usually take several minutes. While waiting, each new line of
        build output is passed to ``on_build_logs``, and a status check that
        fails temporarily (5xx, 429, or no response) is retried for up to two
        minutes. Sandboxes are created
        from the finished template by its alias:
        ``Sandbox.create(template=alias)``.

        Args:
            build_timeout: Seconds to wait for the build to finish.

        Raises:
            BuildError: The build failed; the error carries its logs.
            TimeoutError: The build was still running after ``build_timeout``
                seconds. It keeps running; follow it with ``get_build_status``.
            InvalidArgumentError: The template uses ``copy()``, which is not
                supported yet.
        """
        body = build_request_body(template, alias, cpu_count, memory_mb, disk_mb)
        client = _shared_client(api_key, domain)
        resp = client.post("/templates/build", json=body, timeout=request_timeout)
        info = BuildInfo.from_dict(resp.json())
        return _wait_for_build(client, info, build_timeout, on_build_logs, request_timeout)

    @staticmethod
    def build_in_background(
        template: TemplateBase,
        alias: str,
        cpu_count: Optional[int] = None,
        memory_mb: Optional[int] = None,
        disk_mb: Optional[int] = None,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> BuildInfo:
        """Start a template build and return as soon as the server has
        accepted it, with status ``building``. Follow the build with
        ``get_build_status``."""
        body = build_request_body(template, alias, cpu_count, memory_mb, disk_mb)
        client = _shared_client(api_key, domain)
        resp = client.post("/templates/build", json=body, timeout=request_timeout)
        return BuildInfo.from_dict(resp.json())

    @staticmethod
    def rebuild(
        template_id: str,
        on_build_logs: Optional[Callable[[str], None]] = None,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
        build_timeout: float = DEFAULT_BUILD_TIMEOUT,
    ) -> BuildInfo:
        """Re-run the build of a template whose last build failed, and wait
        for it like ``build``.

        Templates are immutable once built, so this is a recovery path only:
        the rebuild reuses the template's stored spec, and a template that is
        ``ready``, or whose build is still running, is refused with
        ``ConflictError``. A failed template keeps its alias — ``build`` with
        the same alias is refused with a ``ConflictError`` naming the template
        to rebuild — and rebuilding is cheaper than deleting it and starting
        over.

        Raises:
            BuildError: The rebuild failed; the error carries its logs.
            ConflictError: The template is not in the ``failed`` state.
            TimeoutError: The build was still running after ``build_timeout``
                seconds. It keeps running; follow it with ``get_build_status``.
        """
        info = Template.rebuild_in_background(
            template_id, api_key=api_key, domain=domain, request_timeout=request_timeout
        )
        client = _shared_client(api_key, domain)
        return _wait_for_build(client, info, build_timeout, on_build_logs, request_timeout)

    @staticmethod
    def rebuild_in_background(
        template_id: str,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> BuildInfo:
        """Queue a rebuild of a failed template and return as soon as the
        server has accepted it, with status ``building``. Follow the build
        with ``get_build_status``. See ``rebuild`` for when a rebuild is
        allowed."""
        if not template_id:
            raise InvalidArgumentError("template_id is required")
        client = _shared_client(api_key, domain)
        resp = client.post(f"/templates/{template_id}/rebuild", timeout=request_timeout)
        return BuildInfo.from_dict(resp.json())

    @staticmethod
    def get_build_status(
        build_id: str,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> TemplateBuildStatus:
        client = _shared_client(api_key, domain)
        resp = client.get(f"/templates/builds/{build_id}", timeout=request_timeout)
        return TemplateBuildStatus.from_dict(resp.json())


def _shared_client(api_key: Optional[str], domain: Optional[str]) -> ApiClient:
    """The shared client for an api_key/domain override, or the env defaults."""
    return get_shared_client(
        ConnectionConfig(
            api_key=api_key or ConnectionConfig().api_key,
            domain=domain or ConnectionConfig.default_domain(),
        )
    )


def _wait_for_build(
    client: ApiClient,
    info: BuildInfo,
    build_timeout: float,
    on_build_logs: Optional[Callable[[str], None]],
    request_timeout: Optional[float],
) -> BuildInfo:
    """Poll a started build until it finishes; the loop ``build`` and
    ``rebuild`` share."""
    watcher = _BuildWatcher(info, build_timeout, on_build_logs)
    done = watcher.start()
    while done is None:
        time.sleep(watcher.poll_interval)
        try:
            resp = client.get(watcher.status_path, timeout=request_timeout)
        except Exception as err:
            watcher.poll_failed(err)
            continue
        done = watcher.observe(TemplateBuildStatus.from_dict(resp.json()))
    return done
