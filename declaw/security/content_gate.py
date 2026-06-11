from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ContentGateConfig:
    """Configuration for the content.scan OPA gate (model/endpoint allowlist).

    Opts a sandbox into content-gate enforcement without requiring an ML
    scanner.  ``enabled`` defaults to False (gate off).  ``domains`` is an
    optional list of hosts to intercept; omit or leave empty to intercept none.
    """

    enabled: bool = False
    domains: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"enabled": self.enabled}
        if self.domains is not None:
            d["domains"] = self.domains
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ContentGateConfig:
        return cls(
            enabled=data.get("enabled", False),
            domains=data.get("domains"),
        )
