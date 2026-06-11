from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

ALL_TRAFFIC: str = "0.0.0.0/0"

_DOMAIN_PATTERN = re.compile(r"^(\*\.)?([a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$")
_AUTO_DNS = "8.8.8.8"


def _is_ip_or_cidr(value: str) -> bool:
    try:
        ipaddress.ip_network(value, strict=False)
        return True
    except ValueError:
        return False


def _is_domain(value: str) -> bool:
    return bool(_DOMAIN_PATTERN.match(value))


def validate_network_entry(entry: str, *, allow_domains: bool = True) -> str:
    """Validate a network entry (IP, CIDR, or domain). Returns the entry if valid."""
    if _is_ip_or_cidr(entry):
        return entry
    if allow_domains and _is_domain(entry):
        return entry
    raise ValueError(
        f"Invalid network entry: '{entry}'. Must be an IP address, CIDR block, "
        f"or domain name (with optional wildcard prefix)."
    )


def domain_matches(pattern: str, hostname: str) -> bool:
    """Check if a hostname matches a domain pattern (supports wildcard prefix)."""
    if pattern == hostname:
        return True
    if pattern.startswith("*."):
        suffix = pattern[1:]  # ".example.com"
        return hostname.endswith(suffix) or hostname == pattern[2:]
    return False


@dataclass
class SandboxNetworkOpts:
    allow_out: List[str] = field(default_factory=list)
    deny_out: List[str] = field(default_factory=list)
    allow_public_traffic: bool = True
    mask_request_host: Optional[str] = None

    def __post_init__(self) -> None:
        for entry in self.allow_out:
            validate_network_entry(entry, allow_domains=True)
        for entry in self.deny_out:
            validate_network_entry(entry, allow_domains=False)

    @property
    def has_domain_rules(self) -> bool:
        return any(_is_domain(e) for e in self.allow_out)

    @property
    def effective_allow_out(self) -> List[str]:
        result = list(self.allow_out)
        if self.has_domain_rules and _AUTO_DNS not in result:
            result.append(_AUTO_DNS)
        return result

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if self.allow_out:
            result["allow_out"] = self.allow_out
        if self.deny_out:
            result["deny_out"] = self.deny_out
        if not self.allow_public_traffic:
            result["allow_public_traffic"] = False
        if self.mask_request_host is not None:
            result["mask_request_host"] = self.mask_request_host
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SandboxNetworkOpts:
        return cls(
            allow_out=data.get("allow_out", []),
            deny_out=data.get("deny_out", []),
            allow_public_traffic=data.get("allow_public_traffic", True),
            mask_request_host=data.get("mask_request_host"),
        )
