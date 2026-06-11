from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class CodeSecurityConfig:
    """Configuration for code security scanning in agent traffic."""

    enabled: bool = False
    threshold: float = 0.6
    excluded_languages: Optional[List[str]] = None  # languages to exclude from detection
    action: str = "log_only"  # "block" | "log_only"
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
        if self.excluded_languages is not None:
            d["excluded_languages"] = self.excluded_languages
        if self.domains is not None:
            d["domains"] = self.domains
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CodeSecurityConfig:
        return cls(
            enabled=data.get("enabled", False),
            threshold=data.get("threshold", 0.6),
            excluded_languages=data.get("excluded_languages"),
            action=data.get("action", "log_only"),
            domains=data.get("domains"),
        )
