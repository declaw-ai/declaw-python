from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Dict, List

DEFAULT_SENSITIVE_PATTERNS: List[str] = [
    "*_KEY",
    "*_SECRET",
    "*_TOKEN",
    "*_PASSWORD",
    "*_CREDENTIALS",
    "API_KEY",
    "SECRET_KEY",
]


@dataclass
class SecureEnvVar:
    key: str
    value: str
    secret: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"key": self.key, "value": self.value, "secret": self.secret}

    def to_safe_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": "***" if self.secret else self.value,
            "secret": self.secret,
        }


@dataclass
class EnvSecurityConfig:
    mask_patterns: List[str] = field(default_factory=lambda: list(DEFAULT_SENSITIVE_PATTERNS))
    auto_mask_in_audit: bool = True

    def is_sensitive(self, key: str) -> bool:
        return any(fnmatch.fnmatch(key.upper(), pat) for pat in self.mask_patterns)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mask_patterns": self.mask_patterns,
            "auto_mask_in_audit": self.auto_mask_in_audit,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EnvSecurityConfig:
        return cls(
            mask_patterns=data.get("mask_patterns", list(DEFAULT_SENSITIVE_PATTERNS)),
            auto_mask_in_audit=data.get("auto_mask_in_audit", True),
        )
