import pytest


@pytest.fixture(scope="session", autouse=True)
def mock_env_vars() -> None:
    """Mock environment variables for testing."""
