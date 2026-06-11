"""OpenAI Agents SDK sandbox backend for declaw.

Enable this module by installing the ``openai-agents`` extra:

    pip install "declaw[openai-agents]"

Usage:

    from declaw.openai import (
        DeclawSandboxClient, DeclawSandboxClientOptions, DeclawSandboxType,
        SecurityPolicy, PIIConfig, InjectionDefenseConfig,
    )

    client = DeclawSandboxClient()
    session = await client.create(
        options=DeclawSandboxClientOptions(
            template="python",
            security=SecurityPolicy(
                pii=PIIConfig(enabled=True, action="redact"),
                injection_defense=InjectionDefenseConfig(enabled=True),
            ),
        ),
    )
"""

from __future__ import annotations

try:
    # Any import from the openai-agents sandbox machinery confirms the
    # optional dependency is present. We defer to sandbox.py for the
    # actual adapter code so stack traces point at real definitions.
    import agents.sandbox.session  # noqa: F401
except ImportError as _err:  # pragma: no cover
    raise ImportError(
        "declaw.openai requires the openai-agents package. "
        "Install it with: pip install 'declaw[openai-agents]'"
    ) from _err


from declaw.openai.mounts import DeclawCloudBucketMountStrategy
from declaw.openai.sandbox import (
    DeclawSandboxClient,
    DeclawSandboxClientOptions,
    DeclawSandboxSession,
    DeclawSandboxSessionState,
    DeclawSandboxTimeouts,
    DeclawSandboxType,
)
from declaw.sandbox.models import SandboxLifecycle
from declaw.sandbox.network import ALL_TRAFFIC, SandboxNetworkOpts

# Convenience re-exports of the security + network knobs so agent authors
# get everything from one namespace without reaching into declaw.security
# or declaw.sandbox.* for the pieces.
from declaw.security import (
    AuditConfig,
    CodeSecurityConfig,
    EnvSecurityConfig,
    InjectionDefenseConfig,
    InvisibleTextConfig,
    NetworkPolicy,
    PIIConfig,
    SecurityPolicy,
    ToxicityConfig,
    TransformationRule,
)
from declaw.security.pii_handler import GuardrailsClient, PIIHandler
from declaw.volumes.main import Volume, VolumeAttachment, Volumes
from declaw.volumes_async.main import AsyncVolumes

__all__ = [
    # Adapter surface
    "DeclawSandboxClient",
    "DeclawSandboxClientOptions",
    "DeclawSandboxSession",
    "DeclawSandboxSessionState",
    "DeclawSandboxTimeouts",
    "DeclawSandboxType",
    "DeclawCloudBucketMountStrategy",
    # Convenience re-exports from the declaw SDK
    "SecurityPolicy",
    "PIIConfig",
    "InjectionDefenseConfig",
    "TransformationRule",
    "NetworkPolicy",
    "AuditConfig",
    "EnvSecurityConfig",
    "ToxicityConfig",
    "CodeSecurityConfig",
    "InvisibleTextConfig",
    "SandboxLifecycle",
    "SandboxNetworkOpts",
    "ALL_TRAFFIC",
    "GuardrailsClient",
    "PIIHandler",
    # Volumes — upload once, attach to the agent's sandbox (or many).
    "Volume",
    "VolumeAttachment",
    "Volumes",
    "AsyncVolumes",
]
