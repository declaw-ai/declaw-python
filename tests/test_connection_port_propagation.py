"""Regression tests: vault/account clients must not drop a non-443 port.

`ConnectionConfig.__post_init__` splits a "host:port" domain into separate
`domain` and `port` attributes. Several call sites rebuilt a ConnectionConfig
from `.domain` alone, which silently discarded a non-default port and sent the
request to :443 — so on any deployment not served on 443 (on-prem, self-hosted,
local dev) vault and account calls failed while sandbox operations worked.

These tests pin the resolved base URL rather than the internals, because the
whole failure mode was a URL that looked right and wasn't. Nothing in the suite
covered this before: reverting the fix left all other tests green, which is
exactly why it shipped.

Note the default 443 path is asserted too. The fix makes `default_domain()`
return "api.declaw.ai:443", so the URL gains an explicit port where it had
none; httpx normalises that out of the Host header, but a regression here
would break ingress vhost routing in production, so it is worth a test.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from declaw.account import AccountClient
from declaw.account_async import AsyncAccountClient
from declaw.connection_config import ConnectionConfig
from declaw.vault import VaultClient
from declaw.vault_async import AsyncVaultClient

CLIENTS = [VaultClient, AsyncVaultClient, AccountClient, AsyncAccountClient]


def _resolved_url(client) -> str:
    """Base URL the client will actually dial."""
    return client._client.config.api_url


@pytest.mark.parametrize("cls", CLIENTS)
def test_non_443_port_is_preserved_from_env(cls, monkeypatch):
    """A non-443 DECLAW_DOMAIN must reach that port, not :443."""
    monkeypatch.setenv("DECLAW_DOMAIN", "localhost:9999")
    monkeypatch.setenv("DECLAW_API_KEY", "test-key")
    assert _resolved_url(cls()) == "http://localhost:9999"


@pytest.mark.parametrize("cls", CLIENTS)
def test_non_443_port_is_preserved_from_explicit_domain(cls, monkeypatch):
    """Same, when the caller passes domain= instead of using the env var."""
    monkeypatch.delenv("DECLAW_DOMAIN", raising=False)
    monkeypatch.setenv("DECLAW_API_KEY", "test-key")
    assert _resolved_url(cls(domain="declaw.internal:8080")) == ("http://declaw.internal:8080")


@pytest.mark.parametrize("cls", CLIENTS)
def test_default_domain_unchanged(cls, monkeypatch):
    """The default path must keep resolving to production on 443."""
    monkeypatch.delenv("DECLAW_DOMAIN", raising=False)
    monkeypatch.setenv("DECLAW_API_KEY", "test-key")
    assert _resolved_url(cls()) == "https://api.declaw.ai:443"


def test_default_domain_helper_round_trips(monkeypatch):
    """`default_domain()` must survive being re-parsed by ConnectionConfig.

    The sandbox clients rebuild a domain as f"{domain}:{port}", so the value
    has to be idempotent under `__post_init__`'s rsplit(":", 1) — including
    for bracketed IPv6, where a naive split would corrupt the host.
    """
    monkeypatch.setenv("DECLAW_API_KEY", "test-key")
    for raw, host, port in [
        ("api.declaw.ai", "api.declaw.ai", 443),
        ("localhost:9999", "localhost", 9999),
        ("[::1]:9999", "[::1]", 9999),
        ("host.example.com:8080", "host.example.com", 8080),
    ]:
        first = ConnectionConfig(domain=raw)
        assert (first.domain, first.port) == (host, port)

        second = ConnectionConfig(domain=f"{first.domain}:{first.port}")
        assert (second.domain, second.port) == (host, port)
        assert second.api_url == first.api_url


@respx.mock
def test_sandbox_create_sends_vault_requests_to_the_right_port(monkeypatch):
    """`Sandbox.create(vault_refs=...)` must resolve vault refs on its own port.

    This drives the real code path in sandbox_sync/main.py rather than
    re-implementing it: the sandbox itself worked while its vault calls
    silently went to :443, so the assertion that matters is which host:port
    the vault request was actually addressed to.

    Only routes on localhost:9999 are registered — a request to :443 raises
    respx's "not mocked" error rather than passing quietly.
    """
    monkeypatch.setenv("DECLAW_DOMAIN", "localhost:9999")
    monkeypatch.setenv("DECLAW_API_KEY", "test-key")
    base = "http://localhost:9999"

    # The ref must be a BARE name: `expand_vault_refs` short-circuits and makes
    # no request at all when every value is already a vault:// URI, which would
    # make this test vacuously green.
    teams = respx.get(f"{base}/teams").mock(
        return_value=httpx.Response(
            200, json={"teams": [{"team_id": "team-def", "name": "default"}]}
        )
    )
    create = respx.post(f"{base}/sandboxes").mock(
        return_value=httpx.Response(
            200,
            json={
                "sandbox_id": "sbx-1",
                "template_id": "tpl-base",
                "status": "running",
            },
        )
    )

    from declaw import Sandbox

    Sandbox.create(vault_refs={"TOKEN": "MY_SECRET"})

    assert teams.called, "vault team resolution never fired"
    assert teams.calls[0].request.url.host == "localhost"
    assert teams.calls[0].request.url.port == 9999

    # And the expansion actually reached the sandbox create body.
    assert create.called
    import json as _json

    body = _json.loads(create.calls[0].request.content)
    assert body["vault_refs"] == {"TOKEN": "vault://team-def/prod/MY_SECRET"}
