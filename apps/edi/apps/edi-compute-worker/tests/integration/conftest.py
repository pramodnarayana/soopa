import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def mock_env_vars() -> None:
    """Mock environment variables for testing."""
    os.environ.setdefault(
        "DATABASE_URL", "postgresql://ucp_admin:ucp_password@localhost:5432/ucp_global"
    )
    os.environ.setdefault(
        "DB_GLOBAL_URL", "postgresql://ucp_admin:ucp_password@localhost:5432/ucp_global"
    )
    os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    os.environ.setdefault("IDENTITY_AUTHORIZATION_URL", "http://localhost")
    os.environ.setdefault("IDENTITY_TOKEN_URL", "http://localhost")
    os.environ.setdefault("IDENTITY_ISSUER", "http://localhost")
    os.environ.setdefault("IDENTITY_JWKS_URL", "http://localhost")
    os.environ.setdefault("IDENTITY_USERINFO_URL", "http://localhost")
    os.environ.setdefault("PUBLIC_BASE_URL", "http://localhost")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    os.environ.setdefault("AWS_SECURITY_TOKEN", "test")
    os.environ.setdefault("AWS_SESSION_TOKEN", "test")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
