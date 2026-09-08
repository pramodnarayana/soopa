import pytest


@pytest.fixture(scope="session", autouse=True)
def fake_aws_credentials() -> None:
    """Fake AWS Credentials for moto/localstack."""
