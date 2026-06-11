"""Custom OPA policy configuration for per-sandbox policy overrides."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class CustomPolicyConfig:
    """Configuration for customer-supplied OPA policies.

    Enables customers to express custom authorization logic (e.g., block `rm -rf`,
    enforce domain allowlists) in OPA Rego, which is evaluated at envd, proxy,
    and guardrails layers.
    """

    enabled: bool = False
    """Enable custom policy evaluation for this sandbox."""

    inline_rego: Optional[str] = None
    """Customer-supplied Rego code appended to platform defaults.

    Example:
        deny_command contains msg if {
            input.action.command in {"rm", "dd"}
            msg := "dangerous command blocked"
        }
    """

    inline_modules: Optional[List[str]] = None
    """List of independent Rego modules, each with its own ``package`` declaration.

    Use this when your policy spans multiple packages — for example a ``cmd``
    package that restricts shell commands alongside a ``network`` package that
    enforces domain allowlists.  Each entry is a complete Rego source string.
    For a single package you can use ``inline_rego`` instead.
    """

    policy_ref: Optional[str] = None
    """Future: reference to a bundled policy (URL, policy ID, version hash)."""

    default_deny: bool = False
    """When the evaluator is unreachable, deny (True) or allow (False).

    Fail-closed (default_deny=True) is safer for security gates.
    Fail-open (default_deny=False) is acceptable for advisory scanners.
    """

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        d: Dict[str, Any] = {
            "enabled": self.enabled,
            "inline_rego": self.inline_rego,
            "policy_ref": self.policy_ref,
            "default_deny": self.default_deny,
        }
        if self.inline_modules is not None:
            d["inline_modules"] = self.inline_modules
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CustomPolicyConfig:
        """Construct a ``CustomPolicyConfig`` from a deserialized dict."""
        return cls(
            enabled=data.get("enabled", False),
            inline_rego=data.get("inline_rego"),
            inline_modules=data.get("inline_modules"),
            policy_ref=data.get("policy_ref"),
            default_deny=data.get("default_deny", False),
        )
