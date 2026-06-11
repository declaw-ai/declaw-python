"""Tests for GovernancePacks sync and async clients."""

from __future__ import annotations

import httpx
import pytest
import respx

from declaw import GovernancePack
from declaw.governance.main import AsyncGovernancePacks, GovernancePacks
from declaw.governance.models import GovernanceAdvisory, GovernanceControl

API_URL = "https://api.test.dev"

PACK_DICT = {
    "name": "owasp-llm-top10",
    "version": "v1",
    "framework": "OWASP Top 10 for LLM Applications (2025)",
    "description": "Guards against the OWASP Top 10 LLM risks.",
    "gates": ["cmd", "network", "content"],
    "enforces": [
        {
            "control": "OWASP-LLM06-ExcessiveAgency",
            "gate": "cmd",
            "rule": "block shell escape patterns",
            "playbook": "Review agent permissions and scope.",
        }
    ],
    "advisory": [
        {
            "control": "OWASP-LLM03-TrainingDataPoisoning",
            "reason": "Requires external data pipeline controls.",
        }
    ],
    "policy_ref": "owasp-llm-top10@v1",
    "seeded": True,
}

LIST_RESP = {"packs": [PACK_DICT]}


@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    monkeypatch.setenv("DECLAW_API_KEY", "test-key")
    monkeypatch.setenv("DECLAW_DOMAIN", "api.test.dev")


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestGovernancePackModels:
    def test_governance_control_from_dict(self):
        ctrl = GovernanceControl.from_dict(PACK_DICT["enforces"][0])
        assert ctrl.control == "OWASP-LLM06-ExcessiveAgency"
        assert ctrl.gate == "cmd"
        assert ctrl.rule == "block shell escape patterns"
        assert ctrl.playbook == "Review agent permissions and scope."

    def test_governance_advisory_from_dict(self):
        adv = GovernanceAdvisory.from_dict(PACK_DICT["advisory"][0])
        assert adv.control == "OWASP-LLM03-TrainingDataPoisoning"
        assert adv.reason == "Requires external data pipeline controls."

    def test_governance_pack_from_dict(self):
        pack = GovernancePack.from_dict(PACK_DICT)
        assert pack.name == "owasp-llm-top10"
        assert pack.version == "v1"
        assert pack.framework == "OWASP Top 10 for LLM Applications (2025)"
        assert pack.description == "Guards against the OWASP Top 10 LLM risks."
        assert pack.gates == ["cmd", "network", "content"]
        assert len(pack.enforces) == 1
        assert isinstance(pack.enforces[0], GovernanceControl)
        assert pack.enforces[0].control == "OWASP-LLM06-ExcessiveAgency"
        assert len(pack.advisory) == 1
        assert isinstance(pack.advisory[0], GovernanceAdvisory)
        assert pack.policy_ref == "owasp-llm-top10@v1"
        assert pack.seeded is True

    def test_governance_pack_from_dict_defaults(self):
        minimal = {"name": "test-pack"}
        pack = GovernancePack.from_dict(minimal)
        assert pack.name == "test-pack"
        assert pack.version == ""
        assert pack.framework == ""
        assert pack.description == ""
        assert pack.gates == []
        assert pack.enforces == []
        assert pack.advisory == []
        assert pack.policy_ref == ""
        assert pack.seeded is False


# ---------------------------------------------------------------------------
# Sync GovernancePacks tests
# ---------------------------------------------------------------------------


class TestGovernancePacksSync:
    @respx.mock
    def test_list_returns_list_of_packs(self):
        respx.get(f"{API_URL}/governance/packs").mock(
            return_value=httpx.Response(200, json=LIST_RESP)
        )
        packs = GovernancePacks.list(api_key="test-key", domain="api.test.dev")
        assert isinstance(packs, list)
        assert len(packs) == 1
        assert isinstance(packs[0], GovernancePack)
        assert packs[0].name == "owasp-llm-top10"

    @respx.mock
    def test_list_empty_response(self):
        respx.get(f"{API_URL}/governance/packs").mock(
            return_value=httpx.Response(200, json={"packs": []})
        )
        packs = GovernancePacks.list(api_key="test-key", domain="api.test.dev")
        assert packs == []

    @respx.mock
    def test_get_returns_single_pack(self):
        respx.get(f"{API_URL}/governance/packs/owasp-llm-top10").mock(
            return_value=httpx.Response(200, json=PACK_DICT)
        )
        pack = GovernancePacks.get("owasp-llm-top10", api_key="test-key", domain="api.test.dev")
        assert isinstance(pack, GovernancePack)
        assert pack.name == "owasp-llm-top10"
        assert pack.seeded is True

    @respx.mock
    def test_list_sends_auth_header(self):
        route = respx.get(f"{API_URL}/governance/packs").mock(
            return_value=httpx.Response(200, json=LIST_RESP)
        )
        GovernancePacks.list(api_key="test-key", domain="api.test.dev")
        assert route.calls[0].request.headers["authorization"] == "Bearer test-key"

    @respx.mock
    def test_list_uses_env_defaults(self):
        respx.get(f"{API_URL}/governance/packs").mock(
            return_value=httpx.Response(200, json=LIST_RESP)
        )
        # Should not raise — env vars set by autouse fixture
        packs = GovernancePacks.list()
        assert len(packs) == 1


# ---------------------------------------------------------------------------
# Async GovernancePacks tests
# ---------------------------------------------------------------------------


class TestGovernancePacksAsync:
    @respx.mock
    @pytest.mark.asyncio
    async def test_async_list_returns_list_of_packs(self):
        respx.get(f"{API_URL}/governance/packs").mock(
            return_value=httpx.Response(200, json=LIST_RESP)
        )
        packs = await AsyncGovernancePacks.list(api_key="test-key", domain="api.test.dev")
        assert isinstance(packs, list)
        assert len(packs) == 1
        assert isinstance(packs[0], GovernancePack)
        assert packs[0].name == "owasp-llm-top10"
        assert packs[0].enforces[0].gate == "cmd"

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_list_empty(self):
        respx.get(f"{API_URL}/governance/packs").mock(
            return_value=httpx.Response(200, json={"packs": []})
        )
        packs = await AsyncGovernancePacks.list(api_key="test-key", domain="api.test.dev")
        assert packs == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_get_returns_single_pack(self):
        respx.get(f"{API_URL}/governance/packs/owasp-llm-top10").mock(
            return_value=httpx.Response(200, json=PACK_DICT)
        )
        pack = await AsyncGovernancePacks.get(
            "owasp-llm-top10", api_key="test-key", domain="api.test.dev"
        )
        assert isinstance(pack, GovernancePack)
        assert pack.policy_ref == "owasp-llm-top10@v1"

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_list_uses_env_defaults(self):
        respx.get(f"{API_URL}/governance/packs").mock(
            return_value=httpx.Response(200, json=LIST_RESP)
        )
        packs = await AsyncGovernancePacks.list()
        assert len(packs) == 1
