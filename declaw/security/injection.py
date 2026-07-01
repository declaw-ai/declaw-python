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
class InjectionJudgeConfig:
    """Tier-2 Gemma LLM-judge config.

    Layered on top of the Tier-1 classifier: the judge adjudicates the
    classifier's flags with session context, removing false positives and
    catching indirect (cross-domain / multi-turn) injection. Disabled by
    default — the classifier alone is the baseline.
    """

    enabled: bool = False
    # Run the judge on every egress, not just classifier flags (costlier;
    # high-assurance sandboxes).
    always: bool = False
    # Natural-language description of what this agent may do. The judge uses it
    # to tell task-aligned requests from injection-induced deviations. Empty →
    # judge on injection signals alone.
    policy: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"enabled": self.enabled}
        if self.always:
            d["always"] = True
        if self.policy:
            d["policy"] = self.policy
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InjectionJudgeConfig":
        return cls(
            enabled=data.get("enabled", False),
            always=data.get("always", False),
            policy=data.get("policy", ""),
        )


@dataclass
class InjectionDefenseConfig:
    enabled: bool = False
    action: str = InjectionAction.LOG_ONLY.value
    sensitivity: str = InjectionSensitivity.MEDIUM.value
    threshold: float = 0.95
    # Scopes injection scanning to these destination hosts. Injection is
    # OPT-IN per domain: with an empty (or unset) list NO injection scanning
    # runs — this is the opposite of PII/toxicity, where an empty list means
    # all egress. Entries support exact hosts ("api.anthropic.com"),
    # "*.suffix.com" wildcards, and "~regex" patterns. Serialized to the JSON
    # key "domains" only when non-empty.
    domains: Optional[List[str]] = None
    judge: Optional[InjectionJudgeConfig] = None
    # Selects a predefined detection posture for the sandbox.
    # Valid values: "strict", "balanced", "permissive", "agentic-tool",
    # "data-egress-sensitive". None/empty string → server default.
    # Serialized to JSON key "injection_mode".
    injection_mode: Optional[str] = None

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
        # Emit only when non-empty: an empty list means "no injection
        # scanning", which is the wire default, so omit it (matches the other
        # SDKs). None and [] are treated identically.
        if self.domains:
            d["domains"] = self.domains
        if self.judge is not None:
            d["judge"] = self.judge.to_dict()
        if self.injection_mode is not None:
            d["injection_mode"] = self.injection_mode
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> InjectionDefenseConfig:
        judge_data = data.get("judge")
        return cls(
            enabled=data.get("enabled", False),
            action=data.get("action", InjectionAction.LOG_ONLY.value),
            sensitivity=data.get("sensitivity", InjectionSensitivity.MEDIUM.value),
            threshold=data.get("threshold", 0.95),
            domains=data.get("domains"),
            judge=InjectionJudgeConfig.from_dict(judge_data) if judge_data else None,
            injection_mode=data.get("injection_mode"),
        )
