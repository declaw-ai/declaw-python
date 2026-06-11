from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class PIIType(str, Enum):
    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    EMAIL = "email"
    PHONE = "phone"
    PERSON_NAME = "person_name"
    API_KEY = "api_key"
    ADDRESS = "address"
    IP_ADDRESS = "ip_address"


class RedactionAction(str, Enum):
    REDACT = "redact"
    BLOCK = "block"
    LOG_ONLY = "log_only"


@dataclass
class PIIConfig:
    enabled: bool = False
    types: List[str] = field(default_factory=lambda: [t.value for t in PIIType])
    action: str = RedactionAction.REDACT.value
    rehydrate_response: bool = True
    domains: Optional[List[str]] = None

    def __post_init__(self) -> None:
        valid_types = {t.value for t in PIIType}
        for t in self.types:
            if t not in valid_types:
                raise ValueError(f"Invalid PII type: '{t}'. Valid types: {sorted(valid_types)}")
        valid_actions = {a.value for a in RedactionAction}
        if self.action not in valid_actions:
            raise ValueError(
                f"Invalid redaction action: '{self.action}'. Valid actions: {sorted(valid_actions)}"
            )

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "enabled": self.enabled,
            "types": self.types,
            "action": self.action,
            "rehydrate_response": self.rehydrate_response,
        }
        if self.domains is not None:
            d["domains"] = self.domains
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PIIConfig:
        return cls(
            enabled=data.get("enabled", False),
            types=data.get("types", [t.value for t in PIIType]),
            action=data.get("action", RedactionAction.REDACT.value),
            rehydrate_response=data.get("rehydrate_response", True),
            domains=data.get("domains"),
        )
