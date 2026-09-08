import pytest


@pytest.fixture(scope="session", autouse=True)
def mock_aws_credentials() -> None:
    """Mock AWS Credentials for moto/localstack."""
