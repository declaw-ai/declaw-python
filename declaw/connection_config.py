from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ConnectionConfig:
    """Configuration for connecting to the Declaw API server."""

    api_key: str = field(default_factory=lambda: os.environ.get("DECLAW_API_KEY", ""))
    domain: str = field(default_factory=lambda: os.environ.get("DECLAW_DOMAIN", "api.declaw.ai"))
    port: int = 443
    api_url: Optional[str] = None
    request_timeout: Optional[float] = None

    def __post_init__(self) -> None:
        if self.api_url is None:
            if ":" in self.domain:
                host, port_str = self.domain.rsplit(":", 1)
                try:
                    self.port = int(port_str)
                    self.domain = host
                except ValueError:
                    pass
            scheme = "https" if self.port == 443 else "http"
            self.api_url = f"{scheme}://{self.domain}:{self.port}"

    @classmethod
    def default_domain(cls) -> str:
        """Return the default domain as 'host:port' (preserves port from env).

        Use this instead of `ConnectionConfig().domain` when reconstructing a
        ConnectionConfig, because `__post_init__` strips the port into a
        separate attribute — so `ConnectionConfig().domain` alone loses it.
        """
        c = cls()
        return f"{c.domain}:{c.port}"
