from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

from declaw.connection_config import ConnectionConfig


class SandboxBase:
    """Base class providing shared properties and URL helpers for sync/async sandboxes."""

    mcp_port = 50005
    default_sandbox_timeout = 300
    default_template = "base"

    def __init__(
        self,
        sandbox_id: str,
        connection_config: ConnectionConfig,
        envd_access_token: Optional[str] = None,
        sandbox_domain: Optional[str] = None,
        traffic_access_token: Optional[str] = None,
    ):
        self._connection_config = connection_config
        self._sandbox_id = sandbox_id
        self._sandbox_domain = sandbox_domain or connection_config.domain
        self._envd_access_token = envd_access_token
        self._traffic_access_token = traffic_access_token

    @property
    def connection_config(self) -> ConnectionConfig:
        return self._connection_config

    @property
    def sandbox_id(self) -> str:
        return self._sandbox_id

    @property
    def sandbox_domain(self) -> str:
        return self._sandbox_domain

    @property
    def traffic_access_token(self) -> Optional[str]:
        return self._traffic_access_token

    @property
    def envd_api_url(self) -> str:
        """Base URL for this sandbox's namespace on the Declaw API.

        All per-sandbox operations (commands, files, file streaming, ports)
        live under this prefix. Callers must attach an ``X-API-Key`` header
        with their Declaw API key.
        """
        return f"{self._connection_config.api_url}/sandboxes/{self._sandbox_id}"

    def get_host(self, port: int) -> str:
        """Return the path-based URL that reverse-proxies to ``port`` inside the sandbox.

        Requires ``allow_public_traffic`` to be enabled on the sandbox's
        network config (the default). The returned URL is authenticated
        via the same API key as all other sandbox operations.
        """
        return f"{self.envd_api_url}/ports/{port}"

    def get_mcp_url(self) -> str:
        """Return the URL for an MCP server listening on port 50005 inside the sandbox."""
        return f"{self.get_host(self.mcp_port)}/mcp"

    def download_url(self, path: str, user: Optional[str] = None) -> str:
        """URL for a streaming GET of ``path`` out of the sandbox.

        Supports files up to 500 MiB. Callers must attach ``X-API-Key``; the
        URL is NOT safe to share with third parties because the API key is
        required separately.
        """
        params = {"path": path}
        if user:
            params["username"] = user
        return f"{self.envd_api_url}/files/raw?{urlencode(params)}"

    def upload_url(self, path: str, user: Optional[str] = None) -> str:
        """URL for a streaming PUT with a raw binary body that writes ``path`` into the sandbox.

        Supports files up to 500 MiB. Same auth note as :meth:`download_url`.
        """
        params = {"path": path}
        if user:
            params["username"] = user
        return f"{self.envd_api_url}/files/raw?{urlencode(params)}"
