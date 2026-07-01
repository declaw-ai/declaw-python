from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from declaw.api.async_client import AsyncApiClient
from declaw.connection_config import ConnectionConfig
from declaw.vault_models import (
    VaultPreset,
    VaultScope,
    VaultSecret,
)

_DEFAULT_TEAM_NAME = "default"
_DEFAULT_ENV_NAME = "prod"


def _scope_to_dict(scope: Union[VaultScope, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(scope, VaultScope):
        return scope.to_dict()
    return scope


class AsyncVaultClient:
    """Async client for Declaw vault management.

    Secrets are stored and referenced by name; the team/environment scoping
    is handled automatically (a single "default" team + "prod" environment
    per account). The secret value is written to the server (which stores it
    in OpenBao) and is never returned after create.

    Usage:
        async with AsyncVaultClient() as client:
            secret = await client.create_secret("sk-...", provider="openai", name="openai")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ):
        defaults = ConnectionConfig()
        config = ConnectionConfig(
            api_key=api_key if api_key is not None else defaults.api_key,
            domain=domain if domain is not None else defaults.domain,
            request_timeout=request_timeout,
        )
        self._client = AsyncApiClient(config)
        # Per-instance cache (no threading needed in async context).
        self._team_id_cache: Optional[str] = None

    # ------------------------------------------------------------------
    # Internal tenancy resolution (team/env are not part of the public API)
    # ------------------------------------------------------------------

    async def _resolve_default_team(self, create: bool = True) -> Optional[str]:
        """Return the "default" team id for this account.

        When *create* is True the team is provisioned if absent.
        Among duplicate team names the oldest is chosen (by created_at)
        so all clients converge on the same record. The result is cached
        on the client instance.
        """
        if self._team_id_cache is not None:
            return self._team_id_cache

        resp = await self._client.get("/teams")
        data = resp.json()
        teams = data.get("teams", [])

        # Pick the oldest "default" team.
        best: Optional[Dict[str, Any]] = None
        best_ts: Optional[datetime] = None
        for t in teams:
            if t.get("name") == _DEFAULT_TEAM_NAME:
                raw_ts = t.get("created_at", "")
                try:
                    ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    ts = datetime(1970, 1, 1, tzinfo=timezone.utc)
                if best is None or ts < best_ts:  # type: ignore[operator]
                    best = t
                    best_ts = ts

        if best is not None:
            self._team_id_cache = best["team_id"]
            return self._team_id_cache

        if not create:
            return None

        # Provision the default team.
        resp = await self._client.post("/teams", json={"name": _DEFAULT_TEAM_NAME})
        self._team_id_cache = resp.json()["team_id"]
        return self._team_id_cache

    async def _ensure_default_env(self, team_id: str) -> None:
        """Ensure the "prod" environment exists on the team.

        A UNIQUE(team_id, name) conflict from a concurrent create is treated
        as success by re-listing and checking again.
        """
        resp = await self._client.get(f"/teams/{team_id}/environments")
        for e in resp.json().get("environments", []):
            if e.get("name") == _DEFAULT_ENV_NAME:
                return

        try:
            await self._client.post(
                f"/teams/{team_id}/environments", json={"name": _DEFAULT_ENV_NAME}
            )
        except Exception:
            # A racing creator may have made it first; re-check.
            resp2 = await self._client.get(f"/teams/{team_id}/environments")
            for e in resp2.json().get("environments", []):
                if e.get("name") == _DEFAULT_ENV_NAME:
                    return
            raise

    async def _resolve_secret_id(self, team_id: str, name: str) -> str:
        """Map a secret name to its secret_id within the default team."""
        resp = await self._client.get(f"/teams/{team_id}/vault/secrets")
        for s in resp.json().get("secrets", []):
            if s.get("name") == name:
                return s["secret_id"]
        raise ValueError(f"vault secret {name!r} not found")

    # ------------------------------------------------------------------
    # Secrets (addressed by name)
    # ------------------------------------------------------------------

    async def create_secret(
        self,
        value: str,
        *,
        name: Optional[str] = None,
        provider: Optional[str] = None,
        scopes: Optional[List[Union[VaultScope, Dict[str, Any]]]] = None,
        rotation_interval_days: int = 0,
    ) -> VaultSecret:
        """Store a secret's value (server-side, in OpenBao) plus its injection scopes.

        Returns metadata only — the value is never returned after create.
        Either *provider* or *scopes* is required.

        Args:
            value: The secret value (required; never returned).
            name: Human-readable name for the secret. Defaults to *provider*
                when *provider* is set and *name* is omitted.
            provider: A preset key (e.g. ``"openai"``), which supplies scopes
                automatically.
            scopes: Explicit injection rules (required when *provider* is
                omitted).
            rotation_interval_days: Rotation policy; 0 means no rotation.

        Returns:
            VaultSecret metadata (value is not included).
        """
        team_id = await self._resolve_default_team(create=True)
        assert team_id is not None  # always non-None when create=True
        await self._ensure_default_env(team_id)

        body: Dict[str, Any] = {"environment": _DEFAULT_ENV_NAME, "value": value}
        if name is not None:
            body["name"] = name
        if provider is not None:
            body["provider"] = provider
        if scopes is not None:
            body["scopes"] = [_scope_to_dict(s) for s in scopes]
        if rotation_interval_days > 0:
            body["rotation_interval_days"] = rotation_interval_days

        resp = await self._client.post(f"/teams/{team_id}/vault/secrets", json=body)
        return VaultSecret.from_dict(resp.json())

    async def list_secrets(self) -> List[VaultSecret]:
        """Return the metadata for all stored secrets.

        Returns an empty list if no secrets have been stored yet (no default
        team exists).
        """
        team_id = await self._resolve_default_team(create=False)
        if team_id is None:
            return []
        resp = await self._client.get(f"/teams/{team_id}/vault/secrets")
        return [VaultSecret.from_dict(s) for s in resp.json().get("secrets", [])]

    async def rotate_secret(self, name: str, value: str) -> None:
        """Replace a secret's value (by name); scopes are unchanged."""
        team_id = await self._resolve_default_team(create=False)
        if team_id is None:
            raise ValueError(f"vault secret {name!r} not found")
        secret_id = await self._resolve_secret_id(team_id, name)
        await self._client.post(
            f"/teams/{team_id}/vault/secrets/{secret_id}/rotate",
            json={"value": value},
        )

    async def delete_secret(self, name: str) -> None:
        """Delete a secret (by name) — metadata + stored value."""
        team_id = await self._resolve_default_team(create=False)
        if team_id is None:
            raise ValueError(f"vault secret {name!r} not found")
        secret_id = await self._resolve_secret_id(team_id, name)
        await self._client.delete(f"/teams/{team_id}/vault/secrets/{secret_id}")

    async def update_scopes(
        self, name: str, scopes: List[Union[VaultScope, Dict[str, Any]]]
    ) -> None:
        """Replace a secret's injection scopes (by name); the value is unchanged."""
        if not scopes:
            raise ValueError("at least one scope is required")
        team_id = await self._resolve_default_team(create=False)
        if team_id is None:
            raise ValueError(f"vault secret {name!r} not found")
        secret_id = await self._resolve_secret_id(team_id, name)
        await self._client.post(
            f"/teams/{team_id}/vault/secrets/{secret_id}/scopes",
            json={"scopes": [_scope_to_dict(s) for s in scopes]},
        )

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------

    async def list_presets(self) -> List[VaultPreset]:
        """Return the built-in provider catalog (templates only, no secret material)."""
        resp = await self._client.get("/vault/presets")
        data = resp.json()
        return [VaultPreset.from_dict(p) for p in data.get("presets", [])]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._client.close()

    async def __aenter__(self) -> AsyncVaultClient:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()


# ---------------------------------------------------------------------------
# Shared async vault_refs expander (used by async sandbox create)
# ---------------------------------------------------------------------------


async def expand_vault_refs_async(client: AsyncVaultClient, refs: Dict[str, str]) -> Dict[str, str]:
    """Rewrite bare secret names in *refs* to full vault:// URIs (async variant).

    Values already in ``vault://`` form are passed through unchanged.
    Bare names are expanded to ``vault://<team_id>/prod/<name>``.

    Args:
        client: An :class:`AsyncVaultClient` instance (used for team resolution).
        refs: Mapping of env-var name -> bare secret name or vault:// URI.

    Returns:
        A new dict with all bare names expanded.

    Raises:
        ValueError: If bare names are present but no default team exists yet.
    """
    if not refs:
        return refs

    needs_team = any(not v.startswith("vault://") for v in refs.values())
    if not needs_team:
        return refs

    team_id = await client._resolve_default_team(create=False)
    if team_id is None:
        raise ValueError(
            "vault_refs contains bare secret names but no vault secrets exist for this account"
        )

    out: Dict[str, str] = {}
    for env_var, ref in refs.items():
        if ref.startswith("vault://"):
            out[env_var] = ref
        else:
            out[env_var] = f"vault://{team_id}/{_DEFAULT_ENV_NAME}/{ref}"
    return out
