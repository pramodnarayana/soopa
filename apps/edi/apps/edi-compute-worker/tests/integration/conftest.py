import pytest


@pytest.fixture(scope="session", autouse=True)
def fake_env_vars() -> None:
    """Fake environment variables for testing."""
