from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from declaw.sandbox.network import SandboxNetworkOpts, validate_network_entry


@dataclass
class NetworkPolicy:
    """Security-layer network policy. Can also be passed via sandbox network opts."""

    allow_out: List[str] = field(default_factory=list)
    deny_out: List[str] = field(default_factory=list)
    allow_public_traffic: bool = True
    mask_request_host: Optional[str] = None

    def __post_init__(self) -> None:
        for entry in self.allow_out:
            validate_network_entry(entry, allow_domains=True)
        for entry in self.deny_out:
            validate_network_entry(entry, allow_domains=False)

    def to_network_opts(self) -> SandboxNetworkOpts:
        return SandboxNetworkOpts(
            allow_out=self.allow_out,
            deny_out=self.deny_out,
            allow_public_traffic=self.allow_public_traffic,
            mask_request_host=self.mask_request_host,
        )

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
    def from_dict(cls, data: Dict[str, Any]) -> NetworkPolicy:
        return cls(
            allow_out=data.get("allow_out", []),
            deny_out=data.get("deny_out", []),
            allow_public_traffic=data.get("allow_public_traffic", True),
            mask_request_host=data.get("mask_request_host"),
        )
