"""Unit tests for the declaw.openai adapter.

These tests don't hit the network — they verify the adapter's static
contract with the openai-agents SDK (subclass relationships,
discriminator registration, option composition), plus the state
ser/de round-trip.
"""

from __future__ import annotations

import pytest

pytest.importorskip("agents", reason="openai-agents is the optional [openai] extra")

from agents.sandbox.session.base_sandbox_session import BaseSandboxSession
from agents.sandbox.session.sandbox_client import (
    BaseSandboxClient,
    BaseSandboxClientOptions,
)
from agents.sandbox.session.sandbox_session_state import SandboxSessionState

from declaw.openai import (
    ALL_TRAFFIC,
    DeclawSandboxClient,
    DeclawSandboxClientOptions,
    DeclawSandboxSession,
    DeclawSandboxSessionState,
    DeclawSandboxTimeouts,
    DeclawSandboxType,
    InjectionDefenseConfig,
    PIIConfig,
    SandboxNetworkOpts,
    SecurityPolicy,
    ToxicityConfig,
)
from declaw.openai.sandbox import _compose_security

# ---------------------------------------------------------------------------
# Subclass + registration contract
# ---------------------------------------------------------------------------


class TestSubclassContract:
    def test_client_is_base_sandbox_client(self) -> None:
        assert issubclass(DeclawSandboxClient, BaseSandboxClient)

    def test_client_backend_id(self) -> None:
        assert DeclawSandboxClient.backend_id == "declaw"

    def test_options_is_base_client_options(self) -> None:
        assert issubclass(DeclawSandboxClientOptions, BaseSandboxClientOptions)

    def test_session_is_base_sandbox_session(self) -> None:
        assert issubclass(DeclawSandboxSession, BaseSandboxSession)

    def test_state_is_sandbox_session_state(self) -> None:
        assert issubclass(DeclawSandboxSessionState, SandboxSessionState)

    def test_options_auto_registered_by_type_discriminator(self) -> None:
        # BaseSandboxClientOptions maintains a registry keyed by `type`.
        registry = BaseSandboxClientOptions._subclass_registry
        assert "declaw" in registry
        assert registry["declaw"] is DeclawSandboxClientOptions

    def test_type_enum_default_value(self) -> None:
        assert DeclawSandboxType.DEFAULT.value == "default"


# ---------------------------------------------------------------------------
# Options defaults + SecurityPolicy composition
# ---------------------------------------------------------------------------


class TestOptions:
    def test_defaults(self) -> None:
        o = DeclawSandboxClientOptions()
        assert o.type == "declaw"
        assert o.template == "base"
        assert o.timeout == 300
        assert o.allow_internet_access is True
        assert o.security is None
        assert o.network is None

    def test_timeouts_orthogonal(self) -> None:
        t = DeclawSandboxTimeouts(exec_timeout_s=60, fast_op_s=5)
        assert t.exec_timeout_s == 60
        assert t.fast_op_s == 5
        # frozen — no mutation
        with pytest.raises(Exception):
            t.fast_op_s = 99  # type: ignore[misc]

    def test_compose_returns_none_without_any_security(self) -> None:
        assert _compose_security(DeclawSandboxClientOptions()) is None

    def test_compose_uses_full_security_policy(self) -> None:
        opts = DeclawSandboxClientOptions(
            security=SecurityPolicy(pii=PIIConfig(enabled=True, action="redact")),
        )
        p = _compose_security(opts)
        assert p is not None
        assert p.pii.enabled is True
        assert p.pii.action == "redact"

    def test_shortcuts_alone_synthesize_policy(self) -> None:
        opts = DeclawSandboxClientOptions(
            pii=PIIConfig(enabled=True, action="block"),
            injection_defense=InjectionDefenseConfig(enabled=True, sensitivity="high"),
        )
        p = _compose_security(opts)
        assert p is not None
        assert p.pii.action == "block"
        assert p.injection_defense.sensitivity == "high"

    def test_shortcut_overrides_policy_field(self) -> None:
        opts = DeclawSandboxClientOptions(
            security=SecurityPolicy(pii=PIIConfig(enabled=True, action="redact")),
            pii=PIIConfig(enabled=True, action="block"),
        )
        p = _compose_security(opts)
        assert p.pii.action == "block"

    def test_toxicity_shortcut(self) -> None:
        opts = DeclawSandboxClientOptions(
            toxicity=ToxicityConfig(enabled=True, threshold=0.8),
        )
        p = _compose_security(opts)
        assert p.toxicity.enabled is True
        assert p.toxicity.threshold == 0.8

    def test_network_passthrough(self) -> None:
        opts = DeclawSandboxClientOptions(
            network=SandboxNetworkOpts(deny_out=[ALL_TRAFFIC]),
        )
        assert opts.network.deny_out == [ALL_TRAFFIC]


# ---------------------------------------------------------------------------
# Session state serialization (JSON round-trip)
# ---------------------------------------------------------------------------


class TestSessionState:
    def _state(self, **overrides) -> DeclawSandboxSessionState:
        return DeclawSandboxSessionState(
            sandbox_id="sbx-test-123",
            template="python",
            # SandboxSessionState requires snapshot + manifest fields too.
            snapshot={"type": "noop", "id": "snap-inline"},
            manifest={},
            **overrides,
        )

    def test_minimum_fields(self) -> None:
        s = self._state()
        assert s.type == "declaw"
        assert s.sandbox_id == "sbx-test-123"
        assert s.snapshot_id is None

    def test_roundtrip_with_snapshot_id(self) -> None:
        s = self._state(snapshot_id="snap-abc")
        dumped = s.model_dump(mode="json")
        assert dumped["type"] == "declaw"
        assert dumped["sandbox_id"] == "sbx-test-123"
        assert dumped["snapshot_id"] == "snap-abc"

    def test_deserialize_via_client(self) -> None:
        client = DeclawSandboxClient()
        payload = {
            "type": "declaw",
            "sandbox_id": "sbx-resume-1",
            "snapshot_id": "snap-resume-1",
            "template": "python",
            "snapshot": {"type": "noop", "id": "snap-inline"},
            "manifest": {},
        }
        state = client.deserialize_session_state(payload)
        assert isinstance(state, DeclawSandboxSessionState)
        assert state.sandbox_id == "sbx-resume-1"
        assert state.snapshot_id == "snap-resume-1"
