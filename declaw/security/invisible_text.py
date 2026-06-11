from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class InvisibleTextConfig:
    """Configuration for invisible/hidden text detection in agent traffic."""

    enabled: bool = False
    action: str = "strip"  # "block" | "strip" | "log_only"
    domains: Optional[List[str]] = None  # which domains to scan (None = all)

    def __post_init__(self) -> None:
        valid_actions = {"block", "strip", "log_only"}
        if self.action not in valid_actions:
            raise ValueError(f"Invalid action: '{self.action}'. Valid: {sorted(valid_actions)}")

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "enabled": self.enabled,
            "action": self.action,
        }
        if self.domains is not None:
            d["domains"] = self.domains
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> InvisibleTextConfig:
        return cls(
            enabled=data.get("enabled", False),
            action=data.get("action", "strip"),
            domains=data.get("domains"),
        )
