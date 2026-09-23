from __future__ import annotations

import asyncio
from typing import Callable, Optional

from declaw.api.async_client import get_shared_async_client
from declaw.connection_config import ConnectionConfig
from declaw.template.main import (
    DEFAULT_BUILD_TIMEOUT,
    BuildInfo,
    TemplateBase,
    TemplateBuildStatus,
    _BuildWatcher,
    build_request_body,
)


class AsyncTemplate:
    """Async template builder and manager."""

    @staticmethod
    async def build(
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
        ``AsyncSandbox.create(template=alias)``.

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
        config = ConnectionConfig(
            api_key=api_key or ConnectionConfig().api_key,
            domain=domain or ConnectionConfig.default_domain(),
        )
        client = await get_shared_async_client(config)
        resp = await client.post("/templates/build", json=body, timeout=request_timeout)
        info = BuildInfo.from_dict(resp.json())

        watcher = _BuildWatcher(info, build_timeout, on_build_logs)
        done = watcher.start()
        while done is None:
            await asyncio.sleep(watcher.poll_interval)
            try:
                resp = await client.get(watcher.status_path, timeout=request_timeout)
            except Exception as err:
                watcher.poll_failed(err)
                continue
            done = watcher.observe(TemplateBuildStatus.from_dict(resp.json()))
        return done

    @staticmethod
    async def build_in_background(
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
        config = ConnectionConfig(
            api_key=api_key or ConnectionConfig().api_key,
            domain=domain or ConnectionConfig.default_domain(),
        )
        client = await get_shared_async_client(config)
        resp = await client.post("/templates/build", json=body, timeout=request_timeout)
        return BuildInfo.from_dict(resp.json())

    @staticmethod
    async def get_build_status(
        build_id: str,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> TemplateBuildStatus:
        config = ConnectionConfig(
            api_key=api_key or ConnectionConfig().api_key,
            domain=domain or ConnectionConfig.default_domain(),
        )
        client = await get_shared_async_client(config)
        resp = await client.get(f"/templates/builds/{build_id}", timeout=request_timeout)
        return TemplateBuildStatus.from_dict(resp.json())
