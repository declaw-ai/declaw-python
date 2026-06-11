from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class AccountInfo:
    """Information about a Declaw Cloud account."""

    owner_id: str
    email: str
    tier: str
    created_at: str

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> AccountInfo:
        return AccountInfo(
            owner_id=data["owner_id"],
            email=data.get("email", ""),
            tier=data.get("tier", ""),
            created_at=data.get("created_at", ""),
        )


@dataclass
class WalletInfo:
    """Wallet balances using the waterfall credit model.

    sandbox_free_micros / guardrails_free_micros are category-specific free
    credits consumed first. balance_micros is the unified paid balance used
    once free credits for a category are exhausted.
    """

    sandbox_free_micros: int
    guardrails_free_micros: int
    balance_micros: int

    @property
    def sandbox_balance_usd(self) -> float:
        return (self.sandbox_free_micros + self.balance_micros) / 1_000_000

    @property
    def guardrails_balance_usd(self) -> float:
        return (self.guardrails_free_micros + self.balance_micros) / 1_000_000

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> WalletInfo:
        return WalletInfo(
            sandbox_free_micros=data.get("sandbox_free_micros", 0),
            guardrails_free_micros=data.get("guardrails_free_micros", 0),
            balance_micros=data.get("balance_micros", 0),
        )


@dataclass
class UsageSummary:
    """Aggregate usage summary for a time range."""

    compute: Dict[str, Any]
    guardrails: Dict[str, Any]
    total_cost_micros: int

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> UsageSummary:
        return UsageSummary(
            compute=data.get("compute", {}),
            guardrails=data.get("guardrails", {}),
            total_cost_micros=data.get("total_cost_micros", 0),
        )


@dataclass
class DailyUsage:
    """Cost breakdown for a single day."""

    date: str
    compute_cost_micros: int
    guardrails_cost_micros: int
    total_cost_micros: int

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> DailyUsage:
        return DailyUsage(
            date=data.get("date", ""),
            compute_cost_micros=data.get("compute_cost_micros", 0),
            guardrails_cost_micros=data.get("guardrails_cost_micros", 0),
            total_cost_micros=data.get("total_cost_micros", 0),
        )


@dataclass
class DepositInfo:
    """Information about a single deposit transaction."""

    deposit_id: str
    wallet_type: str
    amount_micros: int
    status: str
    created_at: str

    @property
    def amount_usd(self) -> float:
        return self.amount_micros / 1_000_000

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> DepositInfo:
        return DepositInfo(
            deposit_id=data.get("deposit_id", ""),
            wallet_type=data.get("wallet_type", ""),
            amount_micros=data.get("amount_micros", 0),
            status=data.get("status", ""),
            created_at=data.get("created_at", ""),
        )


@dataclass
class AccountOverview:
    """High-level overview of an account: tier, active sandboxes, balances, today's costs."""

    owner_id: str
    tier: str
    active_sandboxes: int
    wallet: WalletInfo
    today_compute_cost_micros: int
    today_guardrails_cost_micros: int
    today_total_cost_micros: int

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> AccountOverview:
        wallets = data.get("wallets", data.get("wallet", {}))
        today = data.get("today", {})
        return AccountOverview(
            owner_id=data.get("owner_id", ""),
            tier=data.get("tier", ""),
            active_sandboxes=data.get("active_sandboxes", 0),
            wallet=WalletInfo.from_dict(wallets),
            today_compute_cost_micros=today.get("compute_cost_micros", 0),
            today_guardrails_cost_micros=today.get("guardrails_cost_micros", 0),
            today_total_cost_micros=today.get("total_cost_micros", 0),
        )
