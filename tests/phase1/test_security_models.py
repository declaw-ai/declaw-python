import datetime
import json
import warnings

import pytest

from declaw import (
    ALL_TRAFFIC,
    AuditConfig,
    AuditEntry,
    CodeSecurityConfig,
    ContentGateConfig,
    CustomPolicyConfig,
    EnvSecurityConfig,
    InjectionAction,
    InjectionDefenseConfig,
    InjectionSensitivity,
    InvisibleTextConfig,
    NetworkPolicy,
    PIIConfig,
    PIIType,
    SecureEnvVar,
    SecurityPolicy,
    ToxicityConfig,
    TransformationRule,
)
from declaw.security.transformations import check_redos


class TestPIIConfig:
    def test_defaults(self):
        cfg = PIIConfig()
        assert cfg.enabled is False
        assert cfg.action == "redact"
        assert cfg.rehydrate_response is True
        assert len(cfg.types) == len(PIIType)

    def test_custom(self):
        cfg = PIIConfig(enabled=True, types=["ssn", "email"], action="block")
        assert cfg.enabled is True
        assert len(cfg.types) == 2

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="Invalid PII type"):
            PIIConfig(types=["invalid_type"])

    def test_invalid_action_raises(self):
        with pytest.raises(ValueError, match="Invalid redaction action"):
            PIIConfig(action="destroy")

    def test_round_trip(self):
        cfg = PIIConfig(enabled=True, types=["ssn", "credit_card"], action="log_only")
        restored = PIIConfig.from_dict(cfg.to_dict())
        assert restored.enabled is True
        assert restored.types == ["ssn", "credit_card"]
        assert restored.action == "log_only"


class TestInjectionDefenseConfig:
    def test_defaults(self):
        cfg = InjectionDefenseConfig()
        assert cfg.enabled is False
        assert cfg.sensitivity == "medium"
        assert cfg.action == "log_only"

    def test_invalid_sensitivity(self):
        with pytest.raises(ValueError, match="Invalid sensitivity"):
            InjectionDefenseConfig(sensitivity="extreme")

    def test_invalid_action(self):
        with pytest.raises(ValueError, match="Invalid action"):
            InjectionDefenseConfig(action="nuke")

    def test_round_trip(self):
        cfg = InjectionDefenseConfig(enabled=True, sensitivity="high", action="block")
        restored = InjectionDefenseConfig.from_dict(cfg.to_dict())
        assert restored.sensitivity == "high"
        assert restored.action == "block"

    def test_action_enum_values(self):
        assert InjectionAction.BLOCK.value == "block"
        assert InjectionAction.LOG_ONLY.value == "log_only"

    def test_audit_backward_compat(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = InjectionDefenseConfig(action="audit")
            assert cfg.action == "log_only"
            assert len(w) == 1
            assert "deprecated" in str(w[0].message).lower()

    def test_sensitivity_enum_values(self):
        assert InjectionSensitivity.LOW.value == "low"
        assert InjectionSensitivity.MEDIUM.value == "medium"
        assert InjectionSensitivity.HIGH.value == "high"

    def test_log_only_action(self):
        cfg = InjectionDefenseConfig(action="log_only")
        assert cfg.action == "log_only"
        d = cfg.to_dict()
        assert d["action"] == "log_only"


class TestTransformationRule:
    def test_basic(self):
        rule = TransformationRule(match=r"sk-\w+", replace="[REDACTED]")
        assert rule.direction == "outbound"

    def test_apply(self):
        rule = TransformationRule(match=r"sk-\w+", replace="[KEY]")
        result = rule.apply("Bearer sk-abc123xyz")
        assert result == "Bearer [KEY]"

    def test_direction_filter(self):
        rule = TransformationRule(match=r"test", replace="x", direction="outbound")
        assert rule.applies_to("outbound") is True
        assert rule.applies_to("inbound") is False

    def test_both_direction(self):
        rule = TransformationRule(match=r"test", replace="x", direction="both")
        assert rule.applies_to("outbound") is True
        assert rule.applies_to("inbound") is True

    def test_invalid_direction(self):
        with pytest.raises(ValueError, match="Invalid direction"):
            TransformationRule(match=r"test", replace="x", direction="sideways")

    def test_invalid_regex(self):
        with pytest.raises(ValueError, match="Invalid regex"):
            TransformationRule(match=r"[invalid", replace="x")

    def test_round_trip(self):
        rule = TransformationRule(match=r"Bearer \w+", replace="Bearer [R]", direction="inbound")
        restored = TransformationRule.from_dict(rule.to_dict())
        assert restored.match == rule.match
        assert restored.replace == rule.replace
        assert restored.direction == "inbound"

    def test_redos_nested_quantifier_plus_plus(self):
        with pytest.raises(ValueError, match="catastrophic backtracking"):
            TransformationRule(match=r"(a+)+", replace="x")

    def test_redos_nested_quantifier_star_plus(self):
        with pytest.raises(ValueError, match="catastrophic backtracking"):
            TransformationRule(match=r"(a*)+", replace="x")

    def test_redos_nested_quantifier_plus_star(self):
        with pytest.raises(ValueError, match="catastrophic backtracking"):
            TransformationRule(match=r"(a+)*", replace="x")

    def test_redos_non_capturing_group(self):
        with pytest.raises(ValueError, match="catastrophic backtracking"):
            TransformationRule(match=r"(?:a+b*)+", replace="x")

    def test_redos_check_function_safe_pattern(self):
        # Should not raise for safe patterns
        check_redos(r"sk-\w+")
        check_redos(r"Bearer [A-Za-z0-9]+")

    def test_redos_pattern_too_long(self):
        long_pattern = "a" * 1001
        with pytest.raises(ValueError, match="too long"):
            check_redos(long_pattern)


class TestToxicityConfig:
    def test_defaults(self):
        cfg = ToxicityConfig()
        assert cfg.enabled is False
        assert cfg.threshold == 0.9
        assert cfg.action == "block"
        assert cfg.domains is None

    def test_custom(self):
        cfg = ToxicityConfig(
            enabled=True, threshold=0.7, action="log_only", domains=["api.openai.com"]
        )
        assert cfg.enabled is True
        assert cfg.threshold == 0.7
        assert cfg.action == "log_only"
        assert cfg.domains == ["api.openai.com"]

    def test_invalid_action(self):
        with pytest.raises(ValueError, match="Invalid action"):
            ToxicityConfig(action="destroy")

    def test_invalid_threshold(self):
        with pytest.raises(ValueError, match="threshold must be between"):
            ToxicityConfig(threshold=1.5)

    def test_to_dict(self):
        cfg = ToxicityConfig(enabled=True, threshold=0.8, action="log_only")
        d = cfg.to_dict()
        assert d == {"enabled": True, "threshold": 0.8, "action": "log_only"}
        assert "domains" not in d

    def test_to_dict_with_domains(self):
        cfg = ToxicityConfig(domains=["example.com"])
        d = cfg.to_dict()
        assert d["domains"] == ["example.com"]

    def test_round_trip(self):
        cfg = ToxicityConfig(enabled=True, threshold=0.75, action="log_only", domains=["a.com"])
        restored = ToxicityConfig.from_dict(cfg.to_dict())
        assert restored.enabled is True
        assert restored.threshold == 0.75
        assert restored.action == "log_only"
        assert restored.domains == ["a.com"]


class TestCodeSecurityConfig:
    def test_defaults(self):
        cfg = CodeSecurityConfig()
        assert cfg.enabled is False
        assert cfg.threshold == 0.6
        assert cfg.action == "log_only"
        assert cfg.excluded_languages is None

    def test_custom(self):
        cfg = CodeSecurityConfig(
            enabled=True, threshold=0.8, excluded_languages=["html"], action="block"
        )
        assert cfg.enabled is True
        assert cfg.threshold == 0.8
        assert cfg.excluded_languages == ["html"]
        assert cfg.action == "block"

    def test_invalid_action(self):
        with pytest.raises(ValueError, match="Invalid action"):
            CodeSecurityConfig(action="nuke")

    def test_invalid_threshold(self):
        with pytest.raises(ValueError, match="threshold must be between"):
            CodeSecurityConfig(threshold=-0.1)

    def test_to_dict(self):
        cfg = CodeSecurityConfig(enabled=True, action="block")
        d = cfg.to_dict()
        assert d == {"enabled": True, "threshold": 0.6, "action": "block"}
        assert "excluded_languages" not in d

    def test_to_dict_with_excluded_languages(self):
        cfg = CodeSecurityConfig(excluded_languages=["python", "bash"])
        d = cfg.to_dict()
        assert d["excluded_languages"] == ["python", "bash"]

    def test_round_trip(self):
        cfg = CodeSecurityConfig(
            enabled=True, threshold=0.9, excluded_languages=["sql"], action="block"
        )
        restored = CodeSecurityConfig.from_dict(cfg.to_dict())
        assert restored.enabled is True
        assert restored.threshold == 0.9
        assert restored.excluded_languages == ["sql"]
        assert restored.action == "block"


class TestInvisibleTextConfig:
    def test_defaults(self):
        cfg = InvisibleTextConfig()
        assert cfg.enabled is False
        assert cfg.action == "strip"

    def test_custom(self):
        cfg = InvisibleTextConfig(enabled=True, action="block")
        assert cfg.enabled is True
        assert cfg.action == "block"

    def test_log_only_action(self):
        cfg = InvisibleTextConfig(action="log_only")
        assert cfg.action == "log_only"

    def test_invalid_action(self):
        with pytest.raises(ValueError, match="Invalid action"):
            InvisibleTextConfig(action="destroy")

    def test_to_dict(self):
        cfg = InvisibleTextConfig(enabled=True, action="strip")
        d = cfg.to_dict()
        assert d == {"enabled": True, "action": "strip"}

    def test_round_trip(self):
        cfg = InvisibleTextConfig(enabled=True, action="block")
        restored = InvisibleTextConfig.from_dict(cfg.to_dict())
        assert restored.enabled is True
        assert restored.action == "block"


class TestNetworkPolicy:
    def test_defaults(self):
        p = NetworkPolicy()
        assert p.allow_out == []
        assert p.deny_out == []

    def test_with_domains(self):
        p = NetworkPolicy(
            allow_out=["*.openai.com", "pypi.org"],
            deny_out=[ALL_TRAFFIC],
        )
        opts = p.to_network_opts()
        assert "*.openai.com" in opts.allow_out
        assert opts.has_domain_rules is True

    def test_invalid_deny_domain(self):
        with pytest.raises(ValueError):
            NetworkPolicy(deny_out=["evil.com"])

    def test_round_trip(self):
        p = NetworkPolicy(
            allow_out=["1.1.1.1"],
            deny_out=[ALL_TRAFFIC],
            allow_public_traffic=False,
        )
        restored = NetworkPolicy.from_dict(p.to_dict())
        assert restored.allow_out == ["1.1.1.1"]
        assert restored.allow_public_traffic is False


class TestAuditConfig:
    def test_defaults(self):
        cfg = AuditConfig()
        assert cfg.enabled is True

    def test_round_trip_enabled(self):
        cfg = AuditConfig(enabled=True)
        restored = AuditConfig.from_dict(cfg.to_dict())
        assert restored.enabled is True

    def test_round_trip_disabled(self):
        cfg = AuditConfig(enabled=False)
        restored = AuditConfig.from_dict(cfg.to_dict())
        assert restored.enabled is False

    def test_only_enabled_serialized(self):
        # AuditConfig was stripped to a single field; guard against someone
        # re-adding log_request_body / retention_hours without also wiring
        # backend support. See declaw/docs/template-shipping-bug.md and
        # cleanup package for the global-retention design.
        assert AuditConfig(enabled=True).to_dict() == {"enabled": True}


class TestAuditEntry:
    def test_round_trip(self):
        now = datetime.datetime(2026, 3, 18, 12, 0, 0)
        entry = AuditEntry(
            timestamp=now,
            method="POST",
            url="https://api.openai.com/v1/chat",
            status_code=200,
            pii_redactions=3,
            injection_blocks=1,
        )
        restored = AuditEntry.from_dict(entry.to_dict())
        assert restored.method == "POST"
        assert restored.pii_redactions == 3
        assert restored.injection_blocks == 1


class TestEnvSecurityConfig:
    def test_defaults(self):
        cfg = EnvSecurityConfig()
        assert cfg.auto_mask_in_audit is True
        assert len(cfg.mask_patterns) > 0

    def test_is_sensitive(self):
        cfg = EnvSecurityConfig()
        assert cfg.is_sensitive("OPENAI_API_KEY") is True
        assert cfg.is_sensitive("DATABASE_PASSWORD") is True
        assert cfg.is_sensitive("MY_SECRET") is True
        assert cfg.is_sensitive("AWS_ACCESS_TOKEN") is True
        assert cfg.is_sensitive("HOME") is False
        assert cfg.is_sensitive("PATH") is False

    def test_round_trip(self):
        cfg = EnvSecurityConfig(mask_patterns=["*_KEY"], auto_mask_in_audit=False)
        restored = EnvSecurityConfig.from_dict(cfg.to_dict())
        assert restored.mask_patterns == ["*_KEY"]
        assert restored.auto_mask_in_audit is False


class TestSecureEnvVar:
    def test_normal_var(self):
        v = SecureEnvVar(key="HOME", value="/home/user")
        d = v.to_safe_dict()
        assert d["value"] == "/home/user"

    def test_secret_var(self):
        v = SecureEnvVar(key="API_KEY", value="sk-secret123", secret=True)
        d = v.to_safe_dict()
        assert d["value"] == "***"
        full = v.to_dict()
        assert full["value"] == "sk-secret123"


class TestSecurityPolicy:
    def test_defaults(self):
        policy = SecurityPolicy()
        assert policy.pii.enabled is False
        assert policy.injection_config.enabled is False
        # Audit defaults to on — matches platform behavior (events are always
        # recorded unless a caller explicitly opts out).
        assert policy.audit_config.enabled is True
        assert policy.transformations == []
        assert policy.network is None
        assert policy.toxicity is None
        assert policy.code_security is None
        assert policy.invisible_text is None

    def test_bool_injection_defense(self):
        policy = SecurityPolicy(injection_defense=True)
        assert policy.injection_config.enabled is True

    def test_config_injection_defense(self):
        policy = SecurityPolicy(
            injection_defense=InjectionDefenseConfig(enabled=True, sensitivity="high")
        )
        assert policy.injection_config.sensitivity == "high"

    def test_bool_audit(self):
        policy = SecurityPolicy(audit=True)
        assert policy.audit_config.enabled is True

    def test_requires_tls_interception(self):
        assert SecurityPolicy().requires_tls_interception is False
        assert SecurityPolicy(pii=PIIConfig(enabled=True)).requires_tls_interception is True
        assert (
            SecurityPolicy(
                transformations=[TransformationRule(match=r"x", replace="y")]
            ).requires_tls_interception
            is True
        )

    def test_requires_tls_interception_new_scanners(self):
        assert (
            SecurityPolicy(toxicity=ToxicityConfig(enabled=True)).requires_tls_interception is True
        )
        assert (
            SecurityPolicy(code_security=CodeSecurityConfig(enabled=True)).requires_tls_interception
            is True
        )
        assert (
            SecurityPolicy(
                invisible_text=InvisibleTextConfig(enabled=True)
            ).requires_tls_interception
            is True
        )
        # Disabled scanners should not require TLS
        assert (
            SecurityPolicy(toxicity=ToxicityConfig(enabled=False)).requires_tls_interception
            is False
        )

    def test_full_policy_round_trip(self):
        policy = SecurityPolicy(
            pii=PIIConfig(enabled=True, types=["ssn", "email"], action="redact"),
            injection_defense=InjectionDefenseConfig(enabled=True, sensitivity="high"),
            transformations=[
                TransformationRule(match=r"Bearer sk-\w+", replace="Bearer [R]"),
            ],
            network=NetworkPolicy(
                allow_out=["*.openai.com"],
                deny_out=[ALL_TRAFFIC],
                allow_public_traffic=False,
            ),
            audit=AuditConfig(enabled=True),
            env_security=EnvSecurityConfig(mask_patterns=["*_KEY"]),
        )
        d = policy.to_dict()
        json_str = policy.to_json()
        assert "ssn" in json_str

        restored = SecurityPolicy.from_dict(d)
        assert restored.pii.enabled is True
        assert restored.pii.types == ["ssn", "email"]
        assert restored.injection_config.sensitivity == "high"
        assert len(restored.transformations) == 1
        assert restored.network is not None
        assert restored.network.allow_public_traffic is False
        assert restored.audit_config.enabled is True
        assert restored.env_security.mask_patterns == ["*_KEY"]

    def test_full_policy_with_all_scanners(self):
        policy = SecurityPolicy(
            pii=PIIConfig(enabled=True),
            injection_defense=InjectionDefenseConfig(enabled=True),
            toxicity=ToxicityConfig(enabled=True, threshold=0.8),
            code_security=CodeSecurityConfig(enabled=True, excluded_languages=["html"]),
            invisible_text=InvisibleTextConfig(enabled=True, action="block"),
            audit=True,
        )
        d = policy.to_dict()
        assert "toxicity" in d
        assert d["toxicity"]["enabled"] is True
        assert d["toxicity"]["threshold"] == 0.8
        assert "code_security" in d
        assert d["code_security"]["excluded_languages"] == ["html"]
        assert "invisible_text" in d
        assert d["invisible_text"]["action"] == "block"

        restored = SecurityPolicy.from_dict(d)
        assert restored.toxicity is not None
        assert restored.toxicity.enabled is True
        assert restored.toxicity.threshold == 0.8
        assert restored.code_security is not None
        assert restored.code_security.excluded_languages == ["html"]
        assert restored.invisible_text is not None
        assert restored.invisible_text.action == "block"

    def test_json_serializable(self):
        policy = SecurityPolicy(
            pii=PIIConfig(enabled=True),
            audit=True,
        )
        s = json.dumps(policy.to_dict())
        assert isinstance(s, str)

    def test_json_serializable_with_all_scanners(self):
        policy = SecurityPolicy(
            pii=PIIConfig(enabled=True),
            toxicity=ToxicityConfig(enabled=True),
            code_security=CodeSecurityConfig(enabled=True),
            invisible_text=InvisibleTextConfig(enabled=True),
        )
        s = json.dumps(policy.to_dict())
        assert isinstance(s, str)
        parsed = json.loads(s)
        assert parsed["toxicity"]["enabled"] is True


class TestCustomPolicyConfig:
    def test_defaults(self):
        cfg = CustomPolicyConfig()
        assert cfg.enabled is False
        assert cfg.inline_rego is None
        assert cfg.inline_modules is None
        assert cfg.policy_ref is None
        assert cfg.default_deny is False

    def test_custom_values(self):
        cfg = CustomPolicyConfig(
            enabled=True,
            inline_rego='package cmd\ndeny["blocked"] { true }',
            inline_modules=[
                'package cmd\ndeny["blocked"] { true }',
                'package net\nallow { input.domain == "safe.example.com" }',
            ],
            policy_ref="pol-abc123",
            default_deny=True,
        )
        assert cfg.enabled is True
        assert cfg.default_deny is True
        assert cfg.policy_ref == "pol-abc123"
        assert len(cfg.inline_modules) == 2

    def test_to_dict_omits_inline_modules_when_none(self):
        cfg = CustomPolicyConfig(enabled=True, inline_rego="package x\n")
        d = cfg.to_dict()
        assert "inline_modules" not in d
        assert d["enabled"] is True
        assert d["inline_rego"] == "package x\n"

    def test_to_dict_includes_inline_modules_when_set(self):
        modules = ["package a\n", "package b\n"]
        cfg = CustomPolicyConfig(inline_modules=modules)
        d = cfg.to_dict()
        assert d["inline_modules"] == modules

    def test_round_trip_with_inline_rego_only(self):
        cfg = CustomPolicyConfig(
            enabled=True,
            inline_rego='package cmd\ndeny["x"] { true }',
            default_deny=True,
        )
        restored = CustomPolicyConfig.from_dict(cfg.to_dict())
        assert restored.enabled is True
        assert restored.inline_rego == cfg.inline_rego
        assert restored.inline_modules is None
        assert restored.default_deny is True

    def test_round_trip_with_inline_modules(self):
        modules = [
            'package cmd\ndeny["blocked"] { input.command == "rm" }',
            'package net\nallow { input.domain == "api.openai.com" }',
        ]
        cfg = CustomPolicyConfig(
            enabled=True,
            inline_modules=modules,
            default_deny=False,
        )
        restored = CustomPolicyConfig.from_dict(cfg.to_dict())
        assert restored.enabled is True
        assert restored.inline_modules == modules
        assert restored.default_deny is False

    def test_round_trip_full(self):
        cfg = CustomPolicyConfig(
            enabled=True,
            inline_rego='package main\ndeny["x"] { true }',
            inline_modules=["package extra\n"],
            policy_ref="pol-xyz",
            default_deny=True,
        )
        d = cfg.to_dict()
        restored = CustomPolicyConfig.from_dict(d)
        assert restored.enabled is True
        assert restored.inline_rego == cfg.inline_rego
        assert restored.inline_modules == cfg.inline_modules
        assert restored.policy_ref == cfg.policy_ref
        assert restored.default_deny is True

    def test_from_dict_defaults_on_missing_keys(self):
        restored = CustomPolicyConfig.from_dict({})
        assert restored.enabled is False
        assert restored.inline_rego is None
        assert restored.inline_modules is None
        assert restored.policy_ref is None
        assert restored.default_deny is False


class TestSecurityPolicyCustomPolicy:
    def test_custom_policy_serialized_in_to_dict(self):
        modules = [
            'package cmd\ndeny["blocked"] { input.command == "rm" }',
            'package net\nallow { input.domain == "api.openai.com" }',
        ]
        policy = SecurityPolicy(
            custom_policy=CustomPolicyConfig(
                enabled=True,
                inline_rego='package main\ndeny["x"] { true }',
                inline_modules=modules,
                default_deny=True,
            )
        )
        d = policy.to_dict()
        assert "custom_policy" in d
        cp = d["custom_policy"]
        assert cp["enabled"] is True
        assert cp["default_deny"] is True
        assert cp["inline_modules"] == modules
        assert cp["inline_rego"] == 'package main\ndeny["x"] { true }'

    def test_custom_policy_absent_when_none(self):
        policy = SecurityPolicy()
        d = policy.to_dict()
        assert "custom_policy" not in d

    def test_custom_policy_round_trip_via_security_policy(self):
        modules = [
            'package cmd\ndeny["blocked"] { input.command == "rm" }',
            'package net\nallow { input.domain == "safe.example.com" }',
        ]
        policy = SecurityPolicy(
            custom_policy=CustomPolicyConfig(
                enabled=True,
                inline_rego='package main\ndeny["x"] { true }',
                inline_modules=modules,
                default_deny=True,
            )
        )
        d = policy.to_dict()
        restored = SecurityPolicy.from_dict(d)

        assert restored.custom_policy is not None
        assert restored.custom_policy.enabled is True
        assert restored.custom_policy.default_deny is True
        assert restored.custom_policy.inline_rego == 'package main\ndeny["x"] { true }'
        assert restored.custom_policy.inline_modules == modules

    def test_custom_policy_from_dict_absent(self):
        d = SecurityPolicy().to_dict()
        restored = SecurityPolicy.from_dict(d)
        assert restored.custom_policy is None

    def test_custom_policy_json_serializable(self):
        policy = SecurityPolicy(
            custom_policy=CustomPolicyConfig(
                enabled=True,
                inline_modules=["package a\n", "package b\n"],
                default_deny=False,
            )
        )
        s = json.dumps(policy.to_dict())
        parsed = json.loads(s)
        assert parsed["custom_policy"]["inline_modules"] == ["package a\n", "package b\n"]
        assert parsed["custom_policy"]["enabled"] is True


class TestImportSmoke:
    def test_top_level_imports(self):
        from declaw import (
            ALL_TRAFFIC,
            CustomPolicyConfig,
            SecurityPolicy,
        )

        assert SecurityPolicy is not None
        assert CustomPolicyConfig is not None
        assert ALL_TRAFFIC == "0.0.0.0/0"

    def test_new_scanner_imports(self):
        from declaw import (
            CodeSecurityConfig,
            InjectionSensitivity,
            InvisibleTextConfig,
            ToxicityConfig,
        )

        assert ToxicityConfig is not None
        assert CodeSecurityConfig is not None
        assert InvisibleTextConfig is not None
        assert InjectionSensitivity is not None


class TestContentGateConfig:
    def test_defaults(self):
        cfg = ContentGateConfig()
        assert cfg.enabled is False
        assert cfg.domains is None

    def test_enabled_no_domains(self):
        cfg = ContentGateConfig(enabled=True)
        assert cfg.enabled is True
        assert cfg.domains is None

    def test_enabled_with_domains(self):
        cfg = ContentGateConfig(enabled=True, domains=["api.openai.com", "api.anthropic.com"])
        assert cfg.enabled is True
        assert cfg.domains == ["api.openai.com", "api.anthropic.com"]

    def test_to_dict_no_domains(self):
        cfg = ContentGateConfig(enabled=True)
        d = cfg.to_dict()
        assert d == {"enabled": True}
        assert "domains" not in d

    def test_to_dict_with_domains(self):
        cfg = ContentGateConfig(enabled=True, domains=["api.openai.com"])
        d = cfg.to_dict()
        assert d["enabled"] is True
        assert d["domains"] == ["api.openai.com"]

    def test_round_trip_enabled_with_domains(self):
        cfg = ContentGateConfig(enabled=True, domains=["api.openai.com", "huggingface.co"])
        restored = ContentGateConfig.from_dict(cfg.to_dict())
        assert restored.enabled is True
        assert restored.domains == ["api.openai.com", "huggingface.co"]

    def test_round_trip_disabled_no_domains(self):
        cfg = ContentGateConfig(enabled=False)
        restored = ContentGateConfig.from_dict(cfg.to_dict())
        assert restored.enabled is False
        assert restored.domains is None

    def test_from_dict_defaults_on_missing_keys(self):
        restored = ContentGateConfig.from_dict({})
        assert restored.enabled is False
        assert restored.domains is None


class TestSecurityPolicyContentGate:
    def test_content_gate_default_none(self):
        policy = SecurityPolicy()
        assert policy.content_gate is None

    def test_content_gate_serialized_in_to_dict(self):
        policy = SecurityPolicy(
            content_gate=ContentGateConfig(
                enabled=True,
                domains=["api.openai.com", "api.anthropic.com"],
            )
        )
        d = policy.to_dict()
        assert "content_gate" in d
        cg = d["content_gate"]
        assert cg["enabled"] is True
        assert cg["domains"] == ["api.openai.com", "api.anthropic.com"]

    def test_content_gate_absent_when_none(self):
        policy = SecurityPolicy()
        d = policy.to_dict()
        assert "content_gate" not in d

    def test_content_gate_no_domains_omits_domains_key(self):
        policy = SecurityPolicy(content_gate=ContentGateConfig(enabled=True))
        d = policy.to_dict()
        assert "content_gate" in d
        assert "domains" not in d["content_gate"]

    def test_content_gate_round_trip_via_security_policy(self):
        policy = SecurityPolicy(
            content_gate=ContentGateConfig(
                enabled=True,
                domains=["api.openai.com"],
            )
        )
        d = policy.to_dict()
        restored = SecurityPolicy.from_dict(d)

        assert restored.content_gate is not None
        assert restored.content_gate.enabled is True
        assert restored.content_gate.domains == ["api.openai.com"]

    def test_content_gate_from_dict_absent(self):
        d = SecurityPolicy().to_dict()
        restored = SecurityPolicy.from_dict(d)
        assert restored.content_gate is None

    def test_content_gate_with_other_scanners(self):
        policy = SecurityPolicy(
            toxicity=ToxicityConfig(enabled=True, threshold=0.8),
            invisible_text=InvisibleTextConfig(enabled=True, action="block"),
            content_gate=ContentGateConfig(enabled=True, domains=["api.openai.com"]),
        )
        d = policy.to_dict()
        assert "toxicity" in d
        assert "invisible_text" in d
        assert "content_gate" in d

        restored = SecurityPolicy.from_dict(d)
        assert restored.toxicity is not None and restored.toxicity.enabled is True
        assert restored.invisible_text is not None and restored.invisible_text.enabled is True
        assert restored.content_gate is not None and restored.content_gate.enabled is True
        assert restored.content_gate.domains == ["api.openai.com"]

    def test_content_gate_json_serializable(self):
        policy = SecurityPolicy(
            content_gate=ContentGateConfig(
                enabled=True,
                domains=["api.openai.com", "api.anthropic.com"],
            )
        )
        s = json.dumps(policy.to_dict())
        parsed = json.loads(s)
        assert parsed["content_gate"]["enabled"] is True
        assert parsed["content_gate"]["domains"] == ["api.openai.com", "api.anthropic.com"]


class TestContentGateImportSmoke:
    def test_content_gate_top_level_import(self):
        from declaw import ContentGateConfig
        assert ContentGateConfig is not None

    def test_content_gate_security_module_import(self):
        from declaw.security import ContentGateConfig
        assert ContentGateConfig is not None
