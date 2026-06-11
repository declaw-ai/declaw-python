from __future__ import annotations

import warnings
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class InjectionAction(str, Enum):
    BLOCK = "block"
    LOG_ONLY = "log_only"


class InjectionSensitivity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Backward compatibility: `audit` was the original name for `log_only`.
_ACTION_COMPAT_MAP = {
    "audit": InjectionAction.LOG_ONLY.value,
}


def _normalize_action(action: str) -> str:
    """Normalize action string, mapping deprecated values to current ones."""
    if action in _ACTION_COMPAT_MAP:
        warnings.warn(
            f"InjectionDefenseConfig action '{action}' is deprecated, "
            f"use '{_ACTION_COMPAT_MAP[action]}' instead.",
            DeprecationWarning,
            stacklevel=3,
        )
        return _ACTION_COMPAT_MAP[action]
    return action


@dataclass
class InjectionDefenseConfig:
    enabled: bool = False
    action: str = InjectionAction.LOG_ONLY.value
    sensitivity: str = InjectionSensitivity.MEDIUM.value
    threshold: float = 0.8
    domains: Optional[List[str]] = None

    def __post_init__(self) -> None:
        self.action = _normalize_action(self.action)

        valid_actions = {a.value for a in InjectionAction}
        if self.action not in valid_actions:
            raise ValueError(f"Invalid action: '{self.action}'. Valid: {sorted(valid_actions)}")

        valid_sensitivities = {s.value for s in InjectionSensitivity}
        if self.sensitivity not in valid_sensitivities:
            raise ValueError(
                f"Invalid sensitivity: '{self.sensitivity}'. Valid: {sorted(valid_sensitivities)}"
            )

        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError(f"threshold must be between 0.0 and 1.0, got {self.threshold}")

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "enabled": self.enabled,
            "action": self.action,
            "sensitivity": self.sensitivity,
            "threshold": self.threshold,
        }
        if self.domains is not None:
            d["domains"] = self.domains
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> InjectionDefenseConfig:
        return cls(
            enabled=data.get("enabled", False),
            action=data.get("action", InjectionAction.LOG_ONLY.value),
            sensitivity=data.get("sensitivity", InjectionSensitivity.MEDIUM.value),
            threshold=data.get("threshold", 0.8),
            domains=data.get("domains"),
        )
