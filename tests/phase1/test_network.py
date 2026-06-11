import json

import pytest

from declaw import ALL_TRAFFIC, SandboxNetworkOpts, domain_matches


class TestALLTRAFFIC:
    def test_value(self):
        assert ALL_TRAFFIC == "0.0.0.0/0"


class TestSandboxNetworkOpts:
    def test_defaults(self):
        opts = SandboxNetworkOpts()
        assert opts.allow_out == []
        assert opts.deny_out == []
        assert opts.allow_public_traffic is True
        assert opts.mask_request_host is None

    def test_deny_all_allow_specific(self):
        opts = SandboxNetworkOpts(
            deny_out=[ALL_TRAFFIC],
            allow_out=["1.1.1.1", "8.8.8.0/24"],
        )
        assert ALL_TRAFFIC in opts.deny_out
        assert "1.1.1.1" in opts.allow_out

    def test_domain_allow(self):
        opts = SandboxNetworkOpts(
            allow_out=["api.openai.com", "*.anthropic.com"],
            deny_out=[ALL_TRAFFIC],
        )
        assert opts.has_domain_rules is True
        effective = opts.effective_allow_out
        assert "8.8.8.8" in effective

    def test_no_domain_rules(self):
        opts = SandboxNetworkOpts(allow_out=["1.1.1.1"])
        assert opts.has_domain_rules is False
        assert "8.8.8.8" not in opts.effective_allow_out

    def test_invalid_cidr_raises(self):
        with pytest.raises(ValueError):
            SandboxNetworkOpts(allow_out=["not-a-valid-entry"])

    def test_domain_in_deny_raises(self):
        with pytest.raises(ValueError, match="Invalid network entry"):
            SandboxNetworkOpts(deny_out=["evil.com"])

    def test_round_trip(self):
        opts = SandboxNetworkOpts(
            allow_out=["*.github.com", "1.2.3.4"],
            deny_out=[ALL_TRAFFIC],
            allow_public_traffic=False,
            mask_request_host="localhost:${PORT}",
        )
        d = opts.to_dict()
        restored = SandboxNetworkOpts.from_dict(d)
        assert restored.allow_out == opts.allow_out
        assert restored.deny_out == opts.deny_out
        assert restored.allow_public_traffic is False
        assert restored.mask_request_host == "localhost:${PORT}"

    def test_json_serializable(self):
        opts = SandboxNetworkOpts(deny_out=[ALL_TRAFFIC])
        s = json.dumps(opts.to_dict())
        assert "0.0.0.0/0" in s

    def test_wildcard_domain_valid(self):
        opts = SandboxNetworkOpts(allow_out=["*.example.com"])
        assert len(opts.allow_out) == 1

    def test_ip_address_valid(self):
        opts = SandboxNetworkOpts(allow_out=["192.168.1.1"])
        assert len(opts.allow_out) == 1

    def test_cidr_valid(self):
        opts = SandboxNetworkOpts(allow_out=["10.0.0.0/8"])
        assert len(opts.allow_out) == 1


class TestDomainMatches:
    def test_exact_match(self):
        assert domain_matches("api.openai.com", "api.openai.com") is True

    def test_no_match(self):
        assert domain_matches("api.openai.com", "api.anthropic.com") is False

    def test_wildcard_match(self):
        assert domain_matches("*.openai.com", "api.openai.com") is True

    def test_wildcard_match_nested(self):
        assert domain_matches("*.openai.com", "deep.api.openai.com") is True

    def test_wildcard_base_domain(self):
        assert domain_matches("*.openai.com", "openai.com") is True

    def test_wildcard_no_match(self):
        assert domain_matches("*.openai.com", "api.anthropic.com") is False
