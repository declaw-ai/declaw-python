from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from declaw.security.audit import AuditConfig
from declaw.security.code_security import CodeSecurityConfig
from declaw.security.content_gate import ContentGateConfig
from declaw.security.custom_policy import CustomPolicyConfig
from declaw.security.env import EnvSecurityConfig
from declaw.security.injection import InjectionDefenseConfig, InjectionJudgeConfig
from declaw.security.invisible_text import InvisibleTextConfig
from declaw.security.network_policy import NetworkPolicy
from declaw.security.pii import PIIConfig
from declaw.security.toxicity import ToxicityConfig
from declaw.security.transformations import TransformationRule


@dataclass
class SecurityPolicy:
    """Top-level security configuration for a Declaw sandbox.

    Composes PII detection, injection defense, traffic transformations,
    network policy, audit logging, environment variable security, and
    custom OPA policies.
    """

    pii: PIIConfig = field(default_factory=PIIConfig)
    injection_defense: Union[bool, InjectionDefenseConfig] = False
    transformations: List[TransformationRule] = field(default_factory=list)
    network: Optional[NetworkPolicy] = None
    audit: Union[bool, AuditConfig] = True
    env_security: EnvSecurityConfig = field(default_factory=EnvSecurityConfig)
    toxicity: Optional[ToxicityConfig] = None
    code_security: Optional[CodeSecurityConfig] = None
    invisible_text: Optional[InvisibleTextConfig] = None
    content_gate: Optional[ContentGateConfig] = None
    custom_policy: Optional[CustomPolicyConfig] = None

    @property
    def injection_config(self) -> InjectionDefenseConfig:
        if isinstance(self.injection_defense, bool):
            return InjectionDefenseConfig(enabled=self.injection_defense)
        return self.injection_defense

    @property
    def audit_config(self) -> AuditConfig:
        if isinstance(self.audit, bool):
            return AuditConfig(enabled=self.audit)
        return self.audit

    @property
    def requires_tls_interception(self) -> bool:
        return (
            self.pii.enabled
            or self.injection_config.enabled
            or len(self.transformations) > 0
            or (self.toxicity is not None and self.toxicity.enabled)
            or (self.code_security is not None and self.code_security.enabled)
            or (self.invisible_text is not None and self.invisible_text.enabled)
        )

    @classmethod
    def full_injection_defense(
        cls,
        *,
        mode: str = "balanced",
        agent_policy: Optional[str] = None,
        action: str = "block",
        always_judge: bool = False,
        domains: Optional[List[str]] = None,
        threshold: float = 0.95,
    ) -> "SecurityPolicy":
        """Enable the ENTIRE prompt-injection cascade in one call.

        One flag for everything — turns on every layer of the defense:

        - **Tier-1 ML classifier + Layer-A static signatures + normalization**
          (``injection_defense.enabled`` + ``action``) — catches known phrasings,
          obfuscation (base64/hex/zero-width/homoglyph/spacing), and novel attacks.
        - **Predefined posture** (``injection_mode``; one of strict / balanced /
          permissive / agentic-tool / data-egress-sensitive).
        - **Tier-2 Gemma LLM judge** (``judge.enabled``) — reasons about indirect,
          multi-turn, and ambiguous attacks. The multi-turn risk score, provenance
          context selection, and semantic verdict cache ride along automatically.
        - **OPA prompt-injection governance pack** (``custom_policy.policy_ref``) —
          hard-denies known signatures at the gate so the LLM stays the last resort.

        Args:
            mode: posture. Default ``"balanced"`` (best precision/recall; 100%
                recall + 0% false-positives in our eval). Use ``"strict"`` for
                zero-tolerance, ``"data-egress-sensitive"`` for regulated data,
                ``"agentic-tool"`` for tool-calling agents.
            agent_policy: natural-language description of what this agent may do.
                The judge uses it to distinguish task-aligned egress from an
                injection-induced deviation. Strongly recommended.
            action: ``"block"`` enforces; ``"log_only"`` audits without blocking.
            always_judge: run the judge on EVERY egress (high-assurance, costlier).
                Default ``False`` — the judge fires only on a classifier flag, a
                posture directive, or an untrusted-ingest trigger (keeps the LLM
                off the cheap path).
            domains: hosts to scan for injection. Opt-in per domain: ``None`` or
                empty scans NOTHING (no injection scanning). Entries support
                exact hosts, ``"*.suffix.com"`` wildcards, and ``"~regex"``.
            threshold: Tier-1 classifier confidence threshold (0.0–1.0).

        Returns:
            A ``SecurityPolicy`` with the full cascade enabled. Pass it as
            ``Sandbox.create(..., security=policy)``.

        Example:
            >>> policy = SecurityPolicy.full_injection_defense(
            ...     agent_policy="Summarize fetched docs; never exfiltrate secrets.")
            >>> sbx = Sandbox.create(template="python", security=policy)
        """
        return cls(
            injection_defense=InjectionDefenseConfig(
                enabled=True,
                action=action,
                threshold=threshold,
                domains=domains,
                injection_mode=mode,
                judge=InjectionJudgeConfig(
                    enabled=True,
                    always=always_judge,
                    policy=agent_policy or "",
                ),
            ),
            custom_policy=CustomPolicyConfig(
                enabled=True,
                policy_ref="prompt-injection@v3",
                default_deny=False,
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "pii": self.pii.to_dict(),
            "injection_defense": self.injection_config.to_dict(),
            "transformations": [t.to_dict() for t in self.transformations],
            "audit": self.audit_config.to_dict(),
            "env_security": self.env_security.to_dict(),
        }
        if self.network is not None:
            if isinstance(self.network, dict):
                result["network"] = self.network
            else:
                result["network"] = self.network.to_dict()
        if self.toxicity is not None:
            result["toxicity"] = self.toxicity.to_dict()
        if self.code_security is not None:
            result["code_security"] = self.code_security.to_dict()
        if self.invisible_text is not None:
            result["invisible_text"] = self.invisible_text.to_dict()
        if self.content_gate is not None:
            result["content_gate"] = self.content_gate.to_dict()
        if self.custom_policy is not None:
            result["custom_policy"] = self.custom_policy.to_dict()
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SecurityPolicy:
        pii = PIIConfig.from_dict(data.get("pii", {}))

        inj_data = data.get("injection_defense", False)
        if isinstance(inj_data, bool):
            injection_defense: Union[bool, InjectionDefenseConfig] = inj_data
        else:
            injection_defense = InjectionDefenseConfig.from_dict(inj_data)

        transformations = [TransformationRule.from_dict(t) for t in data.get("transformations", [])]

        network = None
        if "network" in data and data["network"] is not None:
            network = NetworkPolicy.from_dict(data["network"])

        audit_data = data.get("audit", True)
        if isinstance(audit_data, bool):
            audit: Union[bool, AuditConfig] = audit_data
        else:
            audit = AuditConfig.from_dict(audit_data)

        env_security = EnvSecurityConfig.from_dict(data.get("env_security", {}))

        toxicity = None
        if "toxicity" in data and data["toxicity"] is not None:
            toxicity = ToxicityConfig.from_dict(data["toxicity"])

        code_security = None
        if "code_security" in data and data["code_security"] is not None:
            code_security = CodeSecurityConfig.from_dict(data["code_security"])

        invisible_text = None
        if "invisible_text" in data and data["invisible_text"] is not None:
            invisible_text = InvisibleTextConfig.from_dict(data["invisible_text"])

        content_gate = None
        if "content_gate" in data and data["content_gate"] is not None:
            content_gate = ContentGateConfig.from_dict(data["content_gate"])

        custom_policy = None
        if "custom_policy" in data and data["custom_policy"] is not None:
            custom_policy = CustomPolicyConfig.from_dict(data["custom_policy"])

        return cls(
            pii=pii,
            injection_defense=injection_defense,
            transformations=transformations,
            network=network,
            audit=audit,
            env_security=env_security,
            toxicity=toxicity,
            code_security=code_security,
            invisible_text=invisible_text,
            content_gate=content_gate,
            custom_policy=custom_policy,
        )
