from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from declaw.api.async_client import get_shared_async_client
from declaw.connection_config import ConnectionConfig
from declaw.template.main import BuildInfo, TemplateBase, TemplateBuildStatus


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
    ) -> BuildInfo:
        config = ConnectionConfig(
            api_key=api_key or ConnectionConfig().api_key,
            domain=domain or ConnectionConfig.default_domain(),
        )
        client = await get_shared_async_client(config)
        body: Dict[str, Any] = {
            "template": template.to_dict(),
            "alias": alias,
        }
        if cpu_count is not None:
            body["cpu_count"] = cpu_count
        if memory_mb is not None:
            body["memory_mb"] = memory_mb
        if disk_mb is not None:
            body["disk_mb"] = disk_mb
        resp = await client.post("/templates/build", json=body, timeout=request_timeout)
        data = resp.json()
        info = BuildInfo.from_dict(data)
        if on_build_logs and "logs" in data:
            for log in data["logs"]:
                on_build_logs(log)
        return info

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
