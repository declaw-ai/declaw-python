"""Tests for AccountClient, AsyncAccountClient, and the 402/429 exception handling."""

from __future__ import annotations

import httpx
import pytest
import respx

from declaw import (
    AccountClient,
    AccountInfo,
    AccountOverview,
    AsyncAccountClient,
    DailyUsage,
    DepositInfo,
    InsufficientBalanceException,
    RateLimitException,
    UsageSummary,
    WalletInfo,
)
from declaw.api.client import ApiClient
from declaw.connection_config import ConnectionConfig

API_URL = "https://api.test.dev"
ACCOUNT_ID = "acct-abc123"

ACCOUNT_RESP = {
    "owner_id": ACCOUNT_ID,
    "email": "test@example.com",
    "tier": "pro",
    "created_at": "2026-01-01T00:00:00Z",
}

OVERVIEW_RESP = {
    "owner_id": ACCOUNT_ID,
    "tier": "pro",
    "active_sandboxes": 3,
    "wallets": {
        "sandbox_free_micros": 50_000_000,
        "guardrails_free_micros": 150_000_000,
        "balance_micros": 0,
    },
    "today": {
        "compute_cost_micros": 1_000_000,
        "guardrails_cost_micros": 500_000,
        "total_cost_micros": 1_500_000,
    },
}

WALLET_RESP = {
    "wallet": {
        "sandbox_free_micros": 50_000_000,
        "guardrails_free_micros": 150_000_000,
        "balance_micros": 0,
    }
}

USAGE_RESP = {
    "compute": {"duration_seconds": 3600},
    "guardrails": {"requests": 100},
    "total_cost_micros": 5_000_000,
}

DAILY_RESP = {
    "days": [
        {
            "date": "2026-04-01",
            "compute_cost_micros": 1_000_000,
            "guardrails_cost_micros": 500_000,
            "total_cost_micros": 1_500_000,
        },
        {
            "date": "2026-04-02",
            "compute_cost_micros": 2_000_000,
            "guardrails_cost_micros": 600_000,
            "total_cost_micros": 2_600_000,
        },
    ]
}

DEPOSITS_RESP = {
    "deposits": [
        {
            "deposit_id": "dep-1",
            "wallet_type": "sandbox",
            "amount_micros": 50_000_000,
            "status": "completed",
            "created_at": "2026-03-01T00:00:00Z",
        }
    ],
    "total": 1,
    "has_more": False,
}


@pytest.fixture
def client():
    return AccountClient(api_key="test-key", domain="api.test.dev")


# ---------------------------------------------------------------------------
# Sync AccountClient tests
# ---------------------------------------------------------------------------


class TestAccountClientGetAccount:
    @respx.mock
    def test_get_account_returns_account_info(self, client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}").mock(
            return_value=httpx.Response(200, json=ACCOUNT_RESP)
        )
        info = client.get_account(ACCOUNT_ID)
        assert isinstance(info, AccountInfo)
        assert info.owner_id == ACCOUNT_ID
        assert info.email == "test@example.com"
        assert info.tier == "pro"

    @respx.mock
    def test_get_account_unwraps_nested_account_key(self, client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}").mock(
            return_value=httpx.Response(200, json={"account": ACCOUNT_RESP})
        )
        info = client.get_account(ACCOUNT_ID)
        assert info.owner_id == ACCOUNT_ID

    @respx.mock
    def test_get_account_caches_account_id(self, client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}").mock(
            return_value=httpx.Response(200, json=ACCOUNT_RESP)
        )
        client.get_account(ACCOUNT_ID)
        assert client._owner_id == ACCOUNT_ID


class TestAccountClientGetOverview:
    @respx.mock
    def test_get_overview_returns_overview(self, client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}/overview").mock(
            return_value=httpx.Response(200, json=OVERVIEW_RESP)
        )
        overview = client.get_overview(ACCOUNT_ID)
        assert isinstance(overview, AccountOverview)
        assert overview.owner_id == ACCOUNT_ID
        assert overview.tier == "pro"
        assert overview.active_sandboxes == 3
        assert isinstance(overview.wallet, WalletInfo)
        assert overview.wallet.sandbox_balance_usd == 50.0
        assert overview.wallet.guardrails_balance_usd == 150.0
        assert overview.today_total_cost_micros == 1_500_000

    @respx.mock
    def test_get_overview_caches_account_id(self, client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}/overview").mock(
            return_value=httpx.Response(200, json=OVERVIEW_RESP)
        )
        client.get_overview(ACCOUNT_ID)
        assert client._owner_id == ACCOUNT_ID


class TestAccountClientGetWallet:
    @respx.mock
    def test_get_wallet_returns_wallet_info(self, client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}/wallet").mock(
            return_value=httpx.Response(200, json=WALLET_RESP)
        )
        wallet = client.get_wallet(ACCOUNT_ID)
        assert isinstance(wallet, WalletInfo)
        assert wallet.sandbox_free_micros == 50_000_000
        assert wallet.guardrails_free_micros == 150_000_000
        assert wallet.balance_micros == 0
        assert wallet.sandbox_balance_usd == 50.0
        assert wallet.guardrails_balance_usd == 150.0


class TestAccountClientGetUsage:
    @respx.mock
    def test_get_usage_returns_summary(self, client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}/usage").mock(
            return_value=httpx.Response(200, json=USAGE_RESP)
        )
        summary = client.get_usage(ACCOUNT_ID)
        assert isinstance(summary, UsageSummary)
        assert summary.total_cost_micros == 5_000_000
        assert summary.compute == {"duration_seconds": 3600}
        assert summary.guardrails == {"requests": 100}

    @respx.mock
    def test_get_usage_passes_date_params(self, client):
        route = respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}/usage").mock(
            return_value=httpx.Response(200, json=USAGE_RESP)
        )
        client.get_usage(ACCOUNT_ID, start="2026-04-01", end="2026-04-30")
        params = dict(route.calls[0].request.url.params)
        assert params["start"] == "2026-04-01"
        assert params["end"] == "2026-04-30"


class TestAccountClientGetDailyUsage:
    @respx.mock
    def test_get_daily_usage_returns_list(self, client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}/usage/daily").mock(
            return_value=httpx.Response(200, json=DAILY_RESP)
        )
        days = client.get_daily_usage(ACCOUNT_ID)
        assert len(days) == 2
        assert all(isinstance(d, DailyUsage) for d in days)
        assert days[0].date == "2026-04-01"
        assert days[0].total_cost_micros == 1_500_000
        assert days[1].date == "2026-04-02"


class TestAccountClientListDeposits:
    @respx.mock
    def test_list_deposits_returns_dict(self, client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}/deposits").mock(
            return_value=httpx.Response(200, json=DEPOSITS_RESP)
        )
        result = client.list_deposits(ACCOUNT_ID)
        assert isinstance(result, dict)
        assert result["total"] == 1
        assert result["has_more"] is False
        deposits = result["deposits"]
        assert len(deposits) == 1
        assert isinstance(deposits[0], DepositInfo)
        assert deposits[0].deposit_id == "dep-1"
        assert deposits[0].wallet_type == "sandbox"
        assert deposits[0].amount_usd == 50.0

    @respx.mock
    def test_list_deposits_passes_pagination_params(self, client):
        route = respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}/deposits").mock(
            return_value=httpx.Response(200, json=DEPOSITS_RESP)
        )
        client.list_deposits(ACCOUNT_ID, limit=5, offset=10)
        params = dict(route.calls[0].request.url.params)
        assert params["limit"] == "5"
        assert params["offset"] == "10"


class TestAccountClientSetAccountId:
    @respx.mock
    def test_set_account_id_used_in_subsequent_calls(self, client):
        client.set_owner_id(ACCOUNT_ID)
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}/overview").mock(
            return_value=httpx.Response(200, json=OVERVIEW_RESP)
        )
        overview = client.get_overview()
        assert overview.owner_id == ACCOUNT_ID

    def test_missing_account_id_raises_value_error(self, client):
        with pytest.raises(ValueError, match="owner_id not set"):
            client.get_overview()


class TestAccountClientContextManager:
    @respx.mock
    def test_context_manager_closes_client(self):
        with AccountClient(api_key="test-key", domain="api.test.dev") as c:
            assert c is not None
        # No error means close() was called successfully


# ---------------------------------------------------------------------------
# 402 / 429 exception tests (sync)
# ---------------------------------------------------------------------------


class TestSyncErrorHandling:
    @pytest.fixture
    def api_client(self):
        config = ConnectionConfig(api_key="test-key", api_url=API_URL)
        return ApiClient(config, max_retries=1)

    @respx.mock
    def test_402_raises_insufficient_balance(self, api_client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}").mock(
            return_value=httpx.Response(
                402, json={"message": "insufficient balance", "wallet_type": "sandbox"}
            )
        )
        with pytest.raises(InsufficientBalanceException) as exc_info:
            api_client.get(f"/accounts/{ACCOUNT_ID}")
        assert "402" in str(exc_info.value)
        assert exc_info.value.wallet_type == "sandbox"

    @respx.mock
    def test_429_raises_rate_limit_exception(self, api_client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}").mock(
            return_value=httpx.Response(
                429,
                json={"message": "rate limit exceeded"},
                headers={"Retry-After": "30"},
            )
        )
        with pytest.raises(RateLimitException) as exc_info:
            api_client.get(f"/accounts/{ACCOUNT_ID}")
        assert "429" in str(exc_info.value)
        assert exc_info.value.retry_after == 30.0

    @respx.mock
    def test_429_without_retry_after_header(self, api_client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}").mock(
            return_value=httpx.Response(429, json={"message": "rate limit exceeded"})
        )
        with pytest.raises(RateLimitException) as exc_info:
            api_client.get(f"/accounts/{ACCOUNT_ID}")
        assert exc_info.value.retry_after is None

    @respx.mock
    def test_insufficient_balance_is_sandbox_exception(self, api_client):
        from declaw.exceptions import SandboxException

        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}").mock(
            return_value=httpx.Response(402, json={"message": "no funds"})
        )
        with pytest.raises(SandboxException):
            api_client.get(f"/accounts/{ACCOUNT_ID}")

    @respx.mock
    def test_rate_limit_is_sandbox_exception(self, api_client):
        from declaw.exceptions import SandboxException

        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}").mock(
            return_value=httpx.Response(429, json={"message": "slow down"})
        )
        with pytest.raises(SandboxException):
            api_client.get(f"/accounts/{ACCOUNT_ID}")


# ---------------------------------------------------------------------------
# Async AccountClient tests
# ---------------------------------------------------------------------------


@pytest.fixture
def async_client():
    return AsyncAccountClient(api_key="test-key", domain="api.test.dev")


class TestAsyncAccountClientGetAccount:
    @respx.mock
    @pytest.mark.asyncio
    async def test_get_account_returns_account_info(self, async_client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}").mock(
            return_value=httpx.Response(200, json=ACCOUNT_RESP)
        )
        info = await async_client.get_account(ACCOUNT_ID)
        assert isinstance(info, AccountInfo)
        assert info.owner_id == ACCOUNT_ID
        assert info.tier == "pro"


class TestAsyncAccountClientGetOverview:
    @respx.mock
    @pytest.mark.asyncio
    async def test_get_overview_returns_overview(self, async_client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}/overview").mock(
            return_value=httpx.Response(200, json=OVERVIEW_RESP)
        )
        overview = await async_client.get_overview(ACCOUNT_ID)
        assert isinstance(overview, AccountOverview)
        assert overview.owner_id == ACCOUNT_ID
        assert overview.wallet.sandbox_balance_usd == 50.0

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_overview_caches_account_id(self, async_client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}/overview").mock(
            return_value=httpx.Response(200, json=OVERVIEW_RESP)
        )
        await async_client.get_overview(ACCOUNT_ID)
        assert async_client._owner_id == ACCOUNT_ID


class TestAsyncAccountClientGetWallet:
    @respx.mock
    @pytest.mark.asyncio
    async def test_get_wallet_returns_wallet_info(self, async_client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}/wallet").mock(
            return_value=httpx.Response(200, json=WALLET_RESP)
        )
        wallet = await async_client.get_wallet(ACCOUNT_ID)
        assert isinstance(wallet, WalletInfo)
        assert wallet.sandbox_balance_usd == 50.0
        assert wallet.guardrails_balance_usd == 150.0


class TestAsyncAccountClientGetUsage:
    @respx.mock
    @pytest.mark.asyncio
    async def test_get_usage_returns_summary(self, async_client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}/usage").mock(
            return_value=httpx.Response(200, json=USAGE_RESP)
        )
        summary = await async_client.get_usage(ACCOUNT_ID)
        assert isinstance(summary, UsageSummary)
        assert summary.total_cost_micros == 5_000_000


class TestAsyncAccountClientGetDailyUsage:
    @respx.mock
    @pytest.mark.asyncio
    async def test_get_daily_usage_returns_list(self, async_client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}/usage/daily").mock(
            return_value=httpx.Response(200, json=DAILY_RESP)
        )
        days = await async_client.get_daily_usage(ACCOUNT_ID)
        assert len(days) == 2
        assert all(isinstance(d, DailyUsage) for d in days)
        assert days[0].date == "2026-04-01"


class TestAsyncAccountClientListDeposits:
    @respx.mock
    @pytest.mark.asyncio
    async def test_list_deposits_returns_dict(self, async_client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}/deposits").mock(
            return_value=httpx.Response(200, json=DEPOSITS_RESP)
        )
        result = await async_client.list_deposits(ACCOUNT_ID)
        assert result["total"] == 1
        assert len(result["deposits"]) == 1
        assert isinstance(result["deposits"][0], DepositInfo)


class TestAsyncErrorHandling:
    @pytest.fixture
    def async_api_client(self):
        from declaw.api.async_client import AsyncApiClient

        config = ConnectionConfig(api_key="test-key", api_url=API_URL)
        return AsyncApiClient(config, max_retries=1)

    @respx.mock
    @pytest.mark.asyncio
    async def test_402_raises_insufficient_balance(self, async_api_client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}").mock(
            return_value=httpx.Response(
                402,
                json={"message": "insufficient balance", "wallet_type": "guardrails"},
            )
        )
        with pytest.raises(InsufficientBalanceException) as exc_info:
            await async_api_client.get(f"/accounts/{ACCOUNT_ID}")
        assert exc_info.value.wallet_type == "guardrails"

    @respx.mock
    @pytest.mark.asyncio
    async def test_429_raises_rate_limit_exception(self, async_api_client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}").mock(
            return_value=httpx.Response(
                429,
                json={"message": "too many requests"},
                headers={"Retry-After": "60"},
            )
        )
        with pytest.raises(RateLimitException) as exc_info:
            await async_api_client.get(f"/accounts/{ACCOUNT_ID}")
        assert exc_info.value.retry_after == 60.0

    @respx.mock
    @pytest.mark.asyncio
    async def test_429_without_retry_after_header(self, async_api_client):
        respx.get(f"{API_URL}/accounts/{ACCOUNT_ID}").mock(
            return_value=httpx.Response(429, json={"message": "too many requests"})
        )
        with pytest.raises(RateLimitException) as exc_info:
            await async_api_client.get(f"/accounts/{ACCOUNT_ID}")
        assert exc_info.value.retry_after is None


class TestAsyncAccountClientContextManager:
    @respx.mock
    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        async with AsyncAccountClient(api_key="test-key", domain="api.test.dev") as c:
            assert c is not None
        # No error means aclose() was called successfully
