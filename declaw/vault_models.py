from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VaultScope:
    """One per-destination injection rule on a secret.

    The egress proxy matches a request host against domain_regex and injects
    the secret as injection_type (bearer|header|basic|query|sigv4|oidc|hmac|
    redis|postgres|mysql|smtp|mongodb).
    """

    domain_regex: str
    injection_type: str = ""
    header_name: str = ""
    value_prefix: str = ""
    basic_username: str = ""
    extra_headers: Dict[str, str] = field(default_factory=dict)
    query_params: Dict[str, str] = field(default_factory=dict)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> VaultScope:
        return VaultScope(
            domain_regex=data.get("domain_regex", ""),
            injection_type=data.get("injection_type", ""),
            header_name=data.get("header_name", ""),
            value_prefix=data.get("value_prefix", ""),
            basic_username=data.get("basic_username", ""),
            extra_headers=data.get("extra_headers", {}),
            query_params=data.get("query_params", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the wire format, omitting empty optional fields."""
        out: Dict[str, Any] = {"domain_regex": self.domain_regex}
        if self.injection_type:
            out["injection_type"] = self.injection_type
        if self.header_name:
            out["header_name"] = self.header_name
        if self.value_prefix:
            out["value_prefix"] = self.value_prefix
        if self.basic_username:
            out["basic_username"] = self.basic_username
        if self.extra_headers:
            out["extra_headers"] = self.extra_headers
        if self.query_params:
            out["query_params"] = self.query_params
        return out


@dataclass
class VaultSecret:
    """Metadata for a stored secret — never the value.

    The value lives server-side (OpenBao) and is not returned after create.
    Secrets are addressed by name; team_id/env_id are parsed from the wire
    but are not part of the public API surface.
    """

    secret_id: str
    name: str
    scopes: List[VaultScope]
    created_at: str
    updated_at: str
    rotated_at: Optional[str]
    rotation_interval_days: int
    rotation_due: bool

    # Internal — populated from wire but not advertised publicly.
    _team_id: str = field(default="", repr=False, compare=False)
    _env_id: str = field(default="", repr=False, compare=False)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> VaultSecret:
        scopes = [
            VaultScope.from_dict(s) if isinstance(s, dict) else s for s in data.get("scopes", [])
        ]
        obj = VaultSecret(
            secret_id=data.get("secret_id", ""),
            name=data.get("name", ""),
            scopes=scopes,
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            rotated_at=data.get("rotated_at"),
            rotation_interval_days=data.get("rotation_interval_days", 0),
            rotation_due=data.get("rotation_due", False),
        )
        obj._team_id = data.get("team_id", "")
        obj._env_id = data.get("env_id", "")
        return obj


@dataclass
class VaultPreset:
    """Built-in provider template (domain + injection rules).

    No secret material is carried; it is used so a caller can store a
    credential by naming the provider and supplying only the value.
    """

    key: str
    name: str
    category: str
    key_hint: str
    docs_url: str
    scopes: List[VaultScope]

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> VaultPreset:
        scopes = [
            VaultScope.from_dict(s) if isinstance(s, dict) else s for s in data.get("scopes", [])
        ]
        return VaultPreset(
            key=data.get("key", ""),
            name=data.get("name", ""),
            category=data.get("category", ""),
            key_hint=data.get("key_hint", ""),
            docs_url=data.get("docs_url", ""),
            scopes=scopes,
        )
