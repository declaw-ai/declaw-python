"""Data models for governance packs returned by GET /governance/packs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class GovernanceControl:
    """A single enforced control within a governance pack gate."""

    control: str
    gate: str
    rule: str
    playbook: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GovernanceControl":
        return cls(
            control=data.get("control", ""),
            gate=data.get("gate", ""),
            rule=data.get("rule", ""),
            playbook=data.get("playbook", ""),
        )


@dataclass
class GovernanceAdvisory:
    """An advisory (non-enforcing) item within a governance pack."""

    control: str
    reason: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GovernanceAdvisory":
        return cls(
            control=data.get("control", ""),
            reason=data.get("reason", ""),
        )


@dataclass
class GovernancePack:
    """Metadata and gate definitions for a single governance pack."""

    name: str
    version: str
    framework: str
    description: str
    gates: List[str]
    enforces: List[GovernanceControl]
    advisory: List[GovernanceAdvisory]
    policy_ref: str
    seeded: bool

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GovernancePack":
        return cls(
            name=data.get("name", ""),
            version=data.get("version", ""),
            framework=data.get("framework", ""),
            description=data.get("description", ""),
            gates=list(data.get("gates") or []),
            enforces=[
                GovernanceControl.from_dict(e) for e in (data.get("enforces") or [])
            ],
            advisory=[
                GovernanceAdvisory.from_dict(a) for a in (data.get("advisory") or [])
            ],
            policy_ref=data.get("policy_ref", ""),
            seeded=bool(data.get("seeded", False)),
        )
