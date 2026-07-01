"""Tests for VaultClient, AsyncVaultClient, and expand_vault_refs helpers.

Mirrors the go-sdk vault_test.go coverage: default-team get-or-create,
create_secret defaults environment=prod, rotate/delete by name, bare-name
expansion in vault_refs.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import httpx
import pytest
import respx

from declaw import (
    AsyncVaultClient,
    VaultClient,
    VaultPreset,
    VaultScope,
    VaultSecret,
    expand_vault_refs,
    expand_vault_refs_async,
)

API_URL = "https://api.test.dev"
TEAM_ID = "team-def"
SECRET_ID = "sec-s3cr3t"

# ---------------------------------------------------------------------------
# Shared fixture payloads
# ---------------------------------------------------------------------------

# Default team pre-existing
TEAMS_RESP = {
    "teams": [
        {
            "team_id": TEAM_ID,
            "name": "default",
            "created_at": "2026-01-01T00:00:00Z",
        }
    ]
}

# Prod env pre-existing
ENVS_RESP = {
    "environments": [{"env_id": "env-prod", "name": "prod", "created_at": "2026-01-01T00:00:00Z"}]
}

SECRET_RESP = {
    "secret_id": SECRET_ID,
    "team_id": TEAM_ID,
    "env_id": "env-prod",
    "name": "openai",
    "scopes": [
        {
            "domain_regex": r"api\.openai\.com",
            "injection_type": "bearer",
        }
    ],
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
    "rotated_at": None,
    "rotation_interval_days": 0,
    "rotation_due": False,
}

PRESET_RESP = {
    "key": "openai",
    "name": "OpenAI",
    "category": "ai",
    "key_hint": "sk-...",
    "docs_url": "https://platform.openai.com/docs/api-reference/authentication",
    "scopes": [
        {
            "domain_regex": r"api\.openai\.com",
            "injection_type": "bearer",
        }
    ],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> VaultClient:
    return VaultClient(api_key="test-key", domain="api.test.dev")


@pytest.fixture
def async_client() -> AsyncVaultClient:
    return AsyncVaultClient(api_key="test-key", domain="api.test.dev")


# ---------------------------------------------------------------------------
# Helper: register the default-team+env resolution routes
# ---------------------------------------------------------------------------


def _mock_default_team(team_id: str = TEAM_ID) -> None:
    """Register GET /teams (returns one default team) and GET .../environments."""
    respx.get(f"{API_URL}/teams").mock(
        return_value=httpx.Response(
            200,
            json={
                "teams": [
                    {
                        "team_id": team_id,
                        "name": "default",
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                ]
            },
        )
    )
    respx.get(f"{API_URL}/teams/{team_id}/environments").mock(
        return_value=httpx.Response(
            200, json={"environments": [{"env_id": "env-prod", "name": "prod"}]}
        )
    )


# ===========================================================================
# Sync VaultClient — resolver
# ===========================================================================


class TestResolveDefaultTeam:
    @respx.mock
    def test_uses_existing_default_team(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json=TEAMS_RESP))
        # No POST /teams should be called.
        team_id = client._resolve_default_team(create=False)
        assert team_id == TEAM_ID

    @respx.mock
    def test_picks_oldest_when_duplicates(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(
            return_value=httpx.Response(
                200,
                json={
                    "teams": [
                        {
                            "team_id": "team-newer",
                            "name": "default",
                            "created_at": "2026-06-01T00:00:00Z",
                        },
                        {
                            "team_id": "team-oldest",
                            "name": "default",
                            "created_at": "2026-01-01T00:00:00Z",
                        },
                    ]
                },
            )
        )
        team_id = client._resolve_default_team(create=False)
        assert team_id == "team-oldest"

    @respx.mock
    def test_returns_none_when_no_team_and_create_false(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json={"teams": []}))
        team_id = client._resolve_default_team(create=False)
        assert team_id is None

    @respx.mock
    def test_creates_team_when_absent_and_create_true(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json={"teams": []}))
        create_route = respx.post(f"{API_URL}/teams").mock(
            return_value=httpx.Response(
                201,
                json={
                    "team_id": "team-new",
                    "name": "default",
                    "created_at": "2026-01-02T00:00:00Z",
                },
            )
        )
        team_id = client._resolve_default_team(create=True)
        assert team_id == "team-new"
        body = json.loads(create_route.calls[0].request.content)
        assert body == {"name": "default"}


class TestEnsureDefaultEnv:
    @respx.mock
    def test_no_op_when_prod_exists(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/teams/{TEAM_ID}/environments").mock(
            return_value=httpx.Response(200, json=ENVS_RESP)
        )
        # No POST should be called — just verifying no exception.
        client._ensure_default_env(TEAM_ID)

    @respx.mock
    def test_creates_prod_when_absent(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/teams/{TEAM_ID}/environments").mock(
            return_value=httpx.Response(200, json={"environments": []})
        )
        create_route = respx.post(f"{API_URL}/teams/{TEAM_ID}/environments").mock(
            return_value=httpx.Response(201, json={"env_id": "env-new", "name": "prod"})
        )
        client._ensure_default_env(TEAM_ID)
        body = json.loads(create_route.calls[0].request.content)
        assert body == {"name": "prod"}


# ===========================================================================
# Sync VaultClient — create_secret
# ===========================================================================


class TestCreateSecret:
    @respx.mock
    def test_uses_default_team_and_prod_env(self, client: VaultClient) -> None:
        _mock_default_team()
        route = respx.post(f"{API_URL}/teams/{TEAM_ID}/vault/secrets").mock(
            return_value=httpx.Response(200, json=SECRET_RESP)
        )
        secret = client.create_secret("sk-test", provider="openai", name="openai")

        assert isinstance(secret, VaultSecret)
        assert secret.secret_id == SECRET_ID
        assert secret.name == "openai"
        assert len(secret.scopes) == 1
        assert isinstance(secret.scopes[0], VaultScope)

        body: Dict[str, Any] = json.loads(route.calls[0].request.content)
        assert body["environment"] == "prod"
        assert body["value"] == "sk-test"
        assert body["provider"] == "openai"

    @respx.mock
    def test_auto_provisions_default_team_and_env(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json={"teams": []}))
        respx.post(f"{API_URL}/teams").mock(
            return_value=httpx.Response(
                201,
                json={
                    "team_id": "team-new",
                    "name": "default",
                    "created_at": "2026-01-02T00:00:00Z",
                },
            )
        )
        respx.get(f"{API_URL}/teams/team-new/environments").mock(
            return_value=httpx.Response(200, json={"environments": []})
        )
        respx.post(f"{API_URL}/teams/team-new/environments").mock(
            return_value=httpx.Response(201, json={"env_id": "env-prod", "name": "prod"})
        )
        route = respx.post(f"{API_URL}/teams/team-new/vault/secrets").mock(
            return_value=httpx.Response(201, json={**SECRET_RESP, "team_id": "team-new"})
        )
        secret = client.create_secret(
            "sk-stripe",
            name="stripe",
            scopes=[VaultScope(domain_regex=r"api\.stripe\.com", injection_type="bearer")],
        )
        assert isinstance(secret, VaultSecret)
        body = json.loads(route.calls[0].request.content)
        assert body["environment"] == "prod"

    @respx.mock
    def test_with_explicit_scopes_as_dataclass(self, client: VaultClient) -> None:
        _mock_default_team()
        route = respx.post(f"{API_URL}/teams/{TEAM_ID}/vault/secrets").mock(
            return_value=httpx.Response(200, json=SECRET_RESP)
        )
        scope = VaultScope(domain_regex=r"api\.openai\.com", injection_type="bearer")
        client.create_secret("sk-test", scopes=[scope])

        body = json.loads(route.calls[0].request.content)
        assert "scopes" in body
        assert body["scopes"][0]["domain_regex"] == r"api\.openai\.com"
        # Empty optional fields must be omitted by to_dict
        assert "header_name" not in body["scopes"][0]
        assert "value_prefix" not in body["scopes"][0]

    @respx.mock
    def test_with_rotation_interval(self, client: VaultClient) -> None:
        _mock_default_team()
        route = respx.post(f"{API_URL}/teams/{TEAM_ID}/vault/secrets").mock(
            return_value=httpx.Response(200, json=SECRET_RESP)
        )
        client.create_secret("sk-test", provider="openai", rotation_interval_days=30)
        body = json.loads(route.calls[0].request.content)
        assert body["rotation_interval_days"] == 30

    @respx.mock
    def test_zero_rotation_omitted(self, client: VaultClient) -> None:
        _mock_default_team()
        route = respx.post(f"{API_URL}/teams/{TEAM_ID}/vault/secrets").mock(
            return_value=httpx.Response(200, json=SECRET_RESP)
        )
        client.create_secret("sk-test", provider="openai")
        body = json.loads(route.calls[0].request.content)
        assert "rotation_interval_days" not in body


# ===========================================================================
# Sync VaultClient — list_secrets
# ===========================================================================


class TestListSecrets:
    @respx.mock
    def test_returns_secrets(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json=TEAMS_RESP))
        respx.get(f"{API_URL}/teams/{TEAM_ID}/vault/secrets").mock(
            return_value=httpx.Response(200, json={"secrets": [SECRET_RESP]})
        )
        secrets = client.list_secrets()
        assert len(secrets) == 1
        assert isinstance(secrets[0], VaultSecret)
        assert secrets[0].secret_id == SECRET_ID

    @respx.mock
    def test_empty_when_no_default_team(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json={"teams": []}))
        secrets = client.list_secrets()
        assert secrets == []


# ===========================================================================
# Sync VaultClient — rotate_secret and delete_secret (by name)
# ===========================================================================


class TestRotateSecretByName:
    @respx.mock
    def test_resolves_name_to_id_and_posts_value(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json=TEAMS_RESP))
        respx.get(f"{API_URL}/teams/{TEAM_ID}/vault/secrets").mock(
            return_value=httpx.Response(
                200,
                json={"secrets": [{"secret_id": "sec-42", "name": "stripe"}]},
            )
        )
        rotate_route = respx.post(f"{API_URL}/teams/{TEAM_ID}/vault/secrets/sec-42/rotate").mock(
            return_value=httpx.Response(200, json={"rotated": True})
        )

        client.rotate_secret("stripe", "new-val")

        body = json.loads(rotate_route.calls[0].request.content)
        assert body == {"value": "new-val"}

    @respx.mock
    def test_raises_when_secret_name_not_found(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json=TEAMS_RESP))
        respx.get(f"{API_URL}/teams/{TEAM_ID}/vault/secrets").mock(
            return_value=httpx.Response(200, json={"secrets": []})
        )
        with pytest.raises(ValueError, match="ghost"):
            client.rotate_secret("ghost", "val")

    @respx.mock
    def test_raises_when_no_team(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json={"teams": []}))
        with pytest.raises(ValueError, match="ghost"):
            client.rotate_secret("ghost", "val")


class TestDeleteSecretByName:
    @respx.mock
    def test_resolves_name_to_id_and_deletes(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json=TEAMS_RESP))
        respx.get(f"{API_URL}/teams/{TEAM_ID}/vault/secrets").mock(
            return_value=httpx.Response(
                200,
                json={"secrets": [{"secret_id": "sec-7", "name": "openai"}]},
            )
        )
        del_route = respx.delete(f"{API_URL}/teams/{TEAM_ID}/vault/secrets/sec-7").mock(
            return_value=httpx.Response(200, json={"deleted": True})
        )

        client.delete_secret("openai")
        assert del_route.called

    @respx.mock
    def test_raises_when_secret_name_not_found(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json=TEAMS_RESP))
        respx.get(f"{API_URL}/teams/{TEAM_ID}/vault/secrets").mock(
            return_value=httpx.Response(200, json={"secrets": []})
        )
        with pytest.raises(ValueError, match="ghost"):
            client.delete_secret("ghost")


# ===========================================================================
# Sync VaultClient — list_presets
# ===========================================================================


class TestListPresets:
    @respx.mock
    def test_returns_presets(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/vault/presets").mock(
            return_value=httpx.Response(200, json={"presets": [PRESET_RESP]})
        )
        presets = client.list_presets()
        assert len(presets) == 1
        assert isinstance(presets[0], VaultPreset)
        p = presets[0]
        assert p.key == "openai"
        assert p.name == "OpenAI"
        assert p.category == "ai"
        assert len(p.scopes) == 1

    @respx.mock
    def test_returns_empty_list(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/vault/presets").mock(
            return_value=httpx.Response(200, json={"presets": []})
        )
        assert client.list_presets() == []


# ===========================================================================
# Sync VaultClient — context manager
# ===========================================================================


class TestVaultClientContextManager:
    @respx.mock
    def test_context_manager_closes_client(self) -> None:
        with VaultClient(api_key="test-key", domain="api.test.dev") as c:
            assert c is not None


# ===========================================================================
# expand_vault_refs (sync)
# ===========================================================================


class TestExpandVaultRefs:
    @respx.mock
    def test_bare_names_expanded_to_vault_uri(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json=TEAMS_RESP))
        result = expand_vault_refs(client, {"OPENAI_API_KEY": "openai"})
        assert result == {"OPENAI_API_KEY": f"vault://{TEAM_ID}/prod/openai"}

    @respx.mock
    def test_already_vault_uri_passed_through(self, client: VaultClient) -> None:
        # No HTTP calls needed for all-vault:// refs.
        result = expand_vault_refs(client, {"KEY": f"vault://{TEAM_ID}/prod/openai"})
        assert result == {"KEY": f"vault://{TEAM_ID}/prod/openai"}

    @respx.mock
    def test_mixed_refs(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json=TEAMS_RESP))
        result = expand_vault_refs(
            client,
            {
                "KEY1": "my-secret",
                "KEY2": f"vault://{TEAM_ID}/prod/other",
            },
        )
        assert result["KEY1"] == f"vault://{TEAM_ID}/prod/my-secret"
        assert result["KEY2"] == f"vault://{TEAM_ID}/prod/other"

    @respx.mock
    def test_empty_refs_returned_unchanged(self, client: VaultClient) -> None:
        result = expand_vault_refs(client, {})
        assert result == {}

    @respx.mock
    def test_raises_when_bare_name_but_no_team(self, client: VaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json={"teams": []}))
        with pytest.raises(ValueError, match="no vault secrets exist"):
            expand_vault_refs(client, {"KEY": "my-secret"})


# ===========================================================================
# Async VaultClient — resolver
# ===========================================================================


class TestAsyncResolveDefaultTeam:
    @respx.mock
    @pytest.mark.asyncio
    async def test_uses_existing_default_team(self, async_client: AsyncVaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json=TEAMS_RESP))
        team_id = await async_client._resolve_default_team(create=False)
        assert team_id == TEAM_ID

    @respx.mock
    @pytest.mark.asyncio
    async def test_picks_oldest_when_duplicates(self, async_client: AsyncVaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(
            return_value=httpx.Response(
                200,
                json={
                    "teams": [
                        {
                            "team_id": "team-newer",
                            "name": "default",
                            "created_at": "2026-06-01T00:00:00Z",
                        },
                        {
                            "team_id": "team-oldest",
                            "name": "default",
                            "created_at": "2026-01-01T00:00:00Z",
                        },
                    ]
                },
            )
        )
        team_id = await async_client._resolve_default_team(create=False)
        assert team_id == "team-oldest"

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_none_when_no_team_and_create_false(
        self, async_client: AsyncVaultClient
    ) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json={"teams": []}))
        assert await async_client._resolve_default_team(create=False) is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_creates_team_when_absent(self, async_client: AsyncVaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json={"teams": []}))
        respx.post(f"{API_URL}/teams").mock(
            return_value=httpx.Response(
                201,
                json={
                    "team_id": "team-new",
                    "name": "default",
                    "created_at": "2026-01-02T00:00:00Z",
                },
            )
        )
        team_id = await async_client._resolve_default_team(create=True)
        assert team_id == "team-new"


# ===========================================================================
# Async VaultClient — create_secret
# ===========================================================================


class TestAsyncCreateSecret:
    @respx.mock
    @pytest.mark.asyncio
    async def test_uses_default_team_and_prod_env(self, async_client: AsyncVaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json=TEAMS_RESP))
        respx.get(f"{API_URL}/teams/{TEAM_ID}/environments").mock(
            return_value=httpx.Response(200, json=ENVS_RESP)
        )
        route = respx.post(f"{API_URL}/teams/{TEAM_ID}/vault/secrets").mock(
            return_value=httpx.Response(200, json=SECRET_RESP)
        )
        secret = await async_client.create_secret("sk-test", provider="openai", name="openai")

        assert isinstance(secret, VaultSecret)
        assert secret.secret_id == SECRET_ID

        body = json.loads(route.calls[0].request.content)
        assert body["environment"] == "prod"
        assert body["value"] == "sk-test"
        assert body["provider"] == "openai"

    @respx.mock
    @pytest.mark.asyncio
    async def test_auto_provisions_team_and_env(self, async_client: AsyncVaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json={"teams": []}))
        respx.post(f"{API_URL}/teams").mock(
            return_value=httpx.Response(
                201,
                json={
                    "team_id": "team-new",
                    "name": "default",
                    "created_at": "2026-01-02T00:00:00Z",
                },
            )
        )
        respx.get(f"{API_URL}/teams/team-new/environments").mock(
            return_value=httpx.Response(200, json={"environments": []})
        )
        respx.post(f"{API_URL}/teams/team-new/environments").mock(
            return_value=httpx.Response(201, json={"env_id": "env-prod", "name": "prod"})
        )
        route = respx.post(f"{API_URL}/teams/team-new/vault/secrets").mock(
            return_value=httpx.Response(201, json={**SECRET_RESP, "team_id": "team-new"})
        )
        secret = await async_client.create_secret(
            "sk-stripe",
            name="stripe",
            scopes=[VaultScope(domain_regex=r"api\.stripe\.com", injection_type="bearer")],
        )
        assert isinstance(secret, VaultSecret)
        body = json.loads(route.calls[0].request.content)
        assert body["environment"] == "prod"


# ===========================================================================
# Async VaultClient — list_secrets
# ===========================================================================


class TestAsyncListSecrets:
    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_secrets(self, async_client: AsyncVaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json=TEAMS_RESP))
        respx.get(f"{API_URL}/teams/{TEAM_ID}/vault/secrets").mock(
            return_value=httpx.Response(200, json={"secrets": [SECRET_RESP]})
        )
        secrets = await async_client.list_secrets()
        assert len(secrets) == 1
        assert isinstance(secrets[0], VaultSecret)

    @respx.mock
    @pytest.mark.asyncio
    async def test_empty_when_no_default_team(self, async_client: AsyncVaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json={"teams": []}))
        secrets = await async_client.list_secrets()
        assert secrets == []


# ===========================================================================
# Async VaultClient — rotate/delete by name
# ===========================================================================


class TestAsyncRotateSecret:
    @respx.mock
    @pytest.mark.asyncio
    async def test_resolves_name_to_id_and_posts(self, async_client: AsyncVaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json=TEAMS_RESP))
        respx.get(f"{API_URL}/teams/{TEAM_ID}/vault/secrets").mock(
            return_value=httpx.Response(
                200,
                json={"secrets": [{"secret_id": "sec-42", "name": "stripe"}]},
            )
        )
        rotate_route = respx.post(f"{API_URL}/teams/{TEAM_ID}/vault/secrets/sec-42/rotate").mock(
            return_value=httpx.Response(200, json={"rotated": True})
        )

        await async_client.rotate_secret("stripe", "new-val")

        body = json.loads(rotate_route.calls[0].request.content)
        assert body == {"value": "new-val"}


class TestAsyncDeleteSecret:
    @respx.mock
    @pytest.mark.asyncio
    async def test_resolves_name_to_id_and_deletes(self, async_client: AsyncVaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json=TEAMS_RESP))
        respx.get(f"{API_URL}/teams/{TEAM_ID}/vault/secrets").mock(
            return_value=httpx.Response(
                200,
                json={"secrets": [{"secret_id": "sec-7", "name": "openai"}]},
            )
        )
        del_route = respx.delete(f"{API_URL}/teams/{TEAM_ID}/vault/secrets/sec-7").mock(
            return_value=httpx.Response(200, json={"deleted": True})
        )

        await async_client.delete_secret("openai")
        assert del_route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_when_no_team(self, async_client: AsyncVaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json={"teams": []}))
        with pytest.raises(ValueError, match="ghost"):
            await async_client.delete_secret("ghost")


# ===========================================================================
# Async VaultClient — presets + context manager
# ===========================================================================


class TestAsyncListPresets:
    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_presets(self, async_client: AsyncVaultClient) -> None:
        respx.get(f"{API_URL}/vault/presets").mock(
            return_value=httpx.Response(200, json={"presets": [PRESET_RESP]})
        )
        presets = await async_client.list_presets()
        assert len(presets) == 1
        assert isinstance(presets[0], VaultPreset)
        assert presets[0].key == "openai"
        assert presets[0].docs_url == (
            "https://platform.openai.com/docs/api-reference/authentication"
        )


class TestAsyncVaultClientContextManager:
    @respx.mock
    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        async with AsyncVaultClient(api_key="test-key", domain="api.test.dev") as c:
            assert c is not None


# ===========================================================================
# expand_vault_refs_async
# ===========================================================================


class TestExpandVaultRefsAsync:
    @respx.mock
    @pytest.mark.asyncio
    async def test_bare_names_expanded(self, async_client: AsyncVaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json=TEAMS_RESP))
        result = await expand_vault_refs_async(async_client, {"KEY": "openai"})
        assert result == {"KEY": f"vault://{TEAM_ID}/prod/openai"}

    @respx.mock
    @pytest.mark.asyncio
    async def test_vault_uris_passed_through(self, async_client: AsyncVaultClient) -> None:
        result = await expand_vault_refs_async(
            async_client, {"KEY": f"vault://{TEAM_ID}/prod/openai"}
        )
        assert result == {"KEY": f"vault://{TEAM_ID}/prod/openai"}

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_when_bare_name_but_no_team(self, async_client: AsyncVaultClient) -> None:
        respx.get(f"{API_URL}/teams").mock(return_value=httpx.Response(200, json={"teams": []}))
        with pytest.raises(ValueError, match="no vault secrets exist"):
            await expand_vault_refs_async(async_client, {"KEY": "my-secret"})


# ===========================================================================
# Model tests
# ===========================================================================


class TestVaultModels:
    def test_vault_scope_to_dict_omits_empty_fields(self) -> None:
        scope = VaultScope(domain_regex=r"api\.example\.com", injection_type="bearer")
        d = scope.to_dict()
        assert d["domain_regex"] == r"api\.example\.com"
        assert d["injection_type"] == "bearer"
        assert "header_name" not in d
        assert "value_prefix" not in d
        assert "basic_username" not in d
        assert "extra_headers" not in d
        assert "query_params" not in d

    def test_vault_scope_to_dict_includes_non_empty_optional_fields(self) -> None:
        scope = VaultScope(
            domain_regex=r"api\.example\.com",
            injection_type="header",
            header_name="X-Api-Key",
            value_prefix="Token",
            extra_headers={"X-Version": "v1"},
            query_params={"format": "json"},
        )
        d = scope.to_dict()
        assert d["header_name"] == "X-Api-Key"
        assert d["value_prefix"] == "Token"
        assert d["extra_headers"] == {"X-Version": "v1"}
        assert d["query_params"] == {"format": "json"}

    def test_vault_secret_from_dict_parses_scopes(self) -> None:
        secret = VaultSecret.from_dict(SECRET_RESP)
        assert len(secret.scopes) == 1
        assert isinstance(secret.scopes[0], VaultScope)
        assert secret.scopes[0].injection_type == "bearer"

    def test_vault_secret_from_dict_no_public_team_env_fields(self) -> None:
        secret = VaultSecret.from_dict(SECRET_RESP)
        # team_id and env_id must not be public dataclass fields
        assert not hasattr(secret, "team_id")
        assert not hasattr(secret, "env_id")
        # But they ARE accessible internally via _team_id/_env_id
        assert secret._team_id == TEAM_ID
        assert secret._env_id == "env-prod"

    def test_vault_secret_optional_rotated_at_none(self) -> None:
        secret = VaultSecret.from_dict(SECRET_RESP)
        assert secret.rotated_at is None
        assert secret.rotation_interval_days == 0
        assert secret.rotation_due is False

    def test_vault_preset_from_dict(self) -> None:
        preset = VaultPreset.from_dict(PRESET_RESP)
        assert preset.key == "openai"
        assert preset.docs_url == "https://platform.openai.com/docs/api-reference/authentication"
        assert len(preset.scopes) == 1
        assert preset.scopes[0].domain_regex == r"api\.openai\.com"
