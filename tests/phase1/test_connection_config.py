from declaw import ConnectionConfig


class TestConnectionConfig:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("DECLAW_DOMAIN", raising=False)
        cfg = ConnectionConfig()
        assert cfg.domain == "api.declaw.ai"
        assert cfg.port == 443
        assert cfg.api_url == "https://api.declaw.ai:443"

    def test_custom_domain(self):
        cfg = ConnectionConfig(domain="custom.example.com", port=8080)
        assert cfg.api_url == "http://custom.example.com:8080"

    def test_explicit_api_url(self):
        cfg = ConnectionConfig(api_url="http://localhost:3000")
        assert cfg.api_url == "http://localhost:3000"

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("DECLAW_API_KEY", "test-key-123")
        cfg = ConnectionConfig()
        assert cfg.api_key == "test-key-123"
