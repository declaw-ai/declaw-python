from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ToxicityConfig:
    """Configuration for toxicity detection in agent traffic."""

    enabled: bool = False
    threshold: float = 0.9
    action: str = "block"  # "block" | "log_only"
    domains: Optional[List[str]] = None  # which domains to scan (None = all)

    def __post_init__(self) -> None:
        valid_actions = {"block", "log_only"}
        if self.action not in valid_actions:
            raise ValueError(f"Invalid action: '{self.action}'. Valid: {sorted(valid_actions)}")
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError(f"threshold must be between 0.0 and 1.0, got {self.threshold}")

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "enabled": self.enabled,
            "threshold": self.threshold,
            "action": self.action,
        }
        if self.domains is not None:
            d["domains"] = self.domains
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToxicityConfig:
        return cls(
            enabled=data.get("enabled", False),
            threshold=data.get("threshold", 0.9),
            action=data.get("action", "block"),
            domains=data.get("domains"),
        )
