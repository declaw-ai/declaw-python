from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class AuditConfig:
    """Toggle for per-sandbox audit logging.

    When enabled, Declaw records lifecycle, network, command, filesystem,
    snapshot, and security events. Set ``enabled=False`` to suppress all
    gated categories; only lifecycle and admin events are still recorded.

    Retention is a platform-wide setting (global 7-day default), not a
    per-sandbox knob. Body logging is not user-configurable today.
    """

    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {"enabled": self.enabled}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AuditConfig:
        return cls(enabled=data.get("enabled", True))


@dataclass
class AuditEntry:
    timestamp: datetime.datetime
    method: str
    url: str
    status_code: int = 0
    pii_redactions: int = 0
    injection_blocks: int = 0
    transformations_applied: int = 0
    direction: str = "outbound"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "method": self.method,
            "url": self.url,
            "status_code": self.status_code,
            "pii_redactions": self.pii_redactions,
            "injection_blocks": self.injection_blocks,
            "transformations_applied": self.transformations_applied,
            "direction": self.direction,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AuditEntry:
        return cls(
            timestamp=datetime.datetime.fromisoformat(data["timestamp"]),
            method=data["method"],
            url=data["url"],
            status_code=data.get("status_code", 0),
            pii_redactions=data.get("pii_redactions", 0),
            injection_blocks=data.get("injection_blocks", 0),
            transformations_applied=data.get("transformations_applied", 0),
            direction=data.get("direction", "outbound"),
        )
