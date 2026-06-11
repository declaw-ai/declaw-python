from __future__ import annotations

from typing import Any, Dict, List, Optional

from declaw.account_models import (
    AccountInfo,
    AccountOverview,
    DailyUsage,
    DepositInfo,
    UsageSummary,
    WalletInfo,
)
from declaw.api.client import ApiClient
from declaw.connection_config import ConnectionConfig


class AccountClient:
    """Client for Declaw Cloud account management.

    Usage:
        client = AccountClient()  # uses DECLAW_API_KEY env var
        overview = client.get_overview("acct-123")
        print(f"Balance: ${overview.wallet.sandbox_balance_usd:.2f}")
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
        self._client = ApiClient(config)
        self._owner_id: Optional[str] = None

    def _resolve_owner_id(self, owner_id: Optional[str]) -> str:
        aid = owner_id or self._owner_id
        if aid is None:
            raise ValueError(
                "owner_id not set. Pass owner_id explicitly or call " "set_owner_id() first."
            )
        return aid

    def set_owner_id(self, owner_id: str) -> None:
        """Cache the owner ID so subsequent calls can omit it."""
        self._owner_id = owner_id

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_account(self, owner_id: Optional[str] = None) -> AccountInfo:
        """Fetch account metadata."""
        aid = self._resolve_owner_id(owner_id)
        resp = self._client.get(f"/accounts/{aid}")
        data = resp.json()
        if "account" in data:
            data = data["account"]
        self._owner_id = data.get("owner_id", aid)
        return AccountInfo.from_dict(data)

    # ------------------------------------------------------------------
    # Wallet
    # ------------------------------------------------------------------

    def get_wallet(self, owner_id: Optional[str] = None) -> WalletInfo:
        """Fetch current wallet balances."""
        aid = self._resolve_owner_id(owner_id)
        resp = self._client.get(f"/accounts/{aid}/wallet")
        data = resp.json()
        wallet_data = data.get("wallet", data)
        return WalletInfo.from_dict(wallet_data)

    # ------------------------------------------------------------------
    # Usage
    # ------------------------------------------------------------------

    def get_usage(
        self,
        owner_id: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> UsageSummary:
        """Fetch aggregated usage summary, optionally filtered by date range."""
        aid = self._resolve_owner_id(owner_id)
        params: Dict[str, Any] = {}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        resp = self._client.get(f"/accounts/{aid}/usage", params=params)
        return UsageSummary.from_dict(resp.json())

    def get_daily_usage(
        self,
        owner_id: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> List[DailyUsage]:
        """Fetch day-by-day usage breakdown."""
        aid = self._resolve_owner_id(owner_id)
        params: Dict[str, Any] = {}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        resp = self._client.get(f"/accounts/{aid}/usage/daily", params=params)
        data = resp.json()
        days = data.get("days", data) if isinstance(data, dict) else data
        return [DailyUsage.from_dict(d) for d in days]

    # ------------------------------------------------------------------
    # Deposits
    # ------------------------------------------------------------------

    def list_deposits(
        self,
        owner_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """List deposit transactions with pagination."""
        aid = self._resolve_owner_id(owner_id)
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        resp = self._client.get(f"/accounts/{aid}/deposits", params=params)
        data = resp.json()
        deposits = [DepositInfo.from_dict(d) for d in data.get("deposits", [])]
        return {
            "deposits": deposits,
            "total": data.get("total", len(deposits)),
            "has_more": data.get("has_more", False),
        }

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------

    def get_overview(self, owner_id: Optional[str] = None) -> AccountOverview:
        """Fetch a combined overview: tier, active sandboxes, balances, today's cost."""
        aid = self._resolve_owner_id(owner_id)
        resp = self._client.get(f"/accounts/{aid}/overview")
        data = resp.json()
        overview = AccountOverview.from_dict(data)
        if overview.owner_id:
            self._owner_id = overview.owner_id
        return overview

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AccountClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
