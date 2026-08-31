import pytest


@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock required environment variables for AppSettings."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.setenv("IDENTITY_AUTHORIZATION_URL", "http://localhost:8080")
    monkeypatch.setenv("IDENTITY_TOKEN_URL", "http://localhost:8080")
    monkeypatch.setenv("IDENTITY_ISSUER", "http://localhost:8080")
    monkeypatch.setenv("IDENTITY_JWKS_URL", "http://localhost:8080")
    monkeypatch.setenv("IDENTITY_USERINFO_URL", "http://localhost:8080")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8080")
