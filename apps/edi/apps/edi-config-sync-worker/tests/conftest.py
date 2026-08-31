import os

import pytest


@pytest.fixture(autouse=True)
def mock_env_vars():
    """Mock required environment variables for AppSettings."""
    os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    os.environ.setdefault("IDENTITY_AUTHORIZATION_URL", "http://localhost:8080")
    os.environ.setdefault("IDENTITY_TOKEN_URL", "http://localhost:8080")
    os.environ.setdefault("IDENTITY_ISSUER", "http://localhost:8080")
    os.environ.setdefault("IDENTITY_JWKS_URL", "http://localhost:8080")
    os.environ.setdefault("IDENTITY_USERINFO_URL", "http://localhost:8080")
    os.environ.setdefault("PUBLIC_BASE_URL", "http://localhost:8080")

    yield
