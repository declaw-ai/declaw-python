"""Governance packs: list and fetch compliance framework gate definitions.

GET /governance/packs          -> {"packs": [...]}   (list all)
GET /governance/packs/:name    -> {...}               (single pack)
"""

from __future__ import annotations

from typing import List, Optional

from declaw.api.async_client import AsyncApiClient, get_shared_async_client
from declaw.api.client import ApiClient, get_shared_client
from declaw.connection_config import ConnectionConfig
from declaw.governance.models import GovernancePack

# ---------------------------------------------------------------------------
# Sync client
# ---------------------------------------------------------------------------


class GovernancePacks:
    """Sync client for the /governance/packs API."""

    @staticmethod
    def _client(
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> ApiClient:
        config = ConnectionConfig(
            api_key=api_key or ConnectionConfig().api_key,
            domain=domain or ConnectionConfig.default_domain(),
            request_timeout=request_timeout,
        )
        return get_shared_client(config)

    @staticmethod
    def list(
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> List[GovernancePack]:
        """Return every available governance pack."""
        client = GovernancePacks._client(
            api_key=api_key, domain=domain, request_timeout=request_timeout
        )
        resp = client.get("/governance/packs", timeout=request_timeout)
        payload = resp.json() or {}
        return [GovernancePack.from_dict(p) for p in payload.get("packs", [])]

    @staticmethod
    def get(
        name: str,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> GovernancePack:
        """Fetch a single governance pack by name."""
        client = GovernancePacks._client(
            api_key=api_key, domain=domain, request_timeout=request_timeout
        )
        resp = client.get(f"/governance/packs/{name}", timeout=request_timeout)
        return GovernancePack.from_dict(resp.json())


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------


async def _async_client(
    api_key: Optional[str],
    domain: Optional[str],
    request_timeout: Optional[float],
) -> AsyncApiClient:
    config = ConnectionConfig(
        api_key=api_key or ConnectionConfig().api_key,
        domain=domain or ConnectionConfig.default_domain(),
        request_timeout=request_timeout,
    )
    return await get_shared_async_client(config)


class AsyncGovernancePacks:
    """Async client for the /governance/packs API."""

    @staticmethod
    async def list(
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> List[GovernancePack]:
        """Return every available governance pack."""
        client = await _async_client(api_key, domain, request_timeout)
        resp = await client.get("/governance/packs", timeout=request_timeout)
        payload = resp.json() or {}
        return [GovernancePack.from_dict(p) for p in payload.get("packs", [])]

    @staticmethod
    async def get(
        name: str,
        *,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> GovernancePack:
        """Fetch a single governance pack by name."""
        client = await _async_client(api_key, domain, request_timeout)
        resp = await client.get(f"/governance/packs/{name}", timeout=request_timeout)
        return GovernancePack.from_dict(resp.json())
