import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def mock_aws_credentials() -> None:
    """Mock AWS Credentials for moto/localstack."""
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    os.environ.setdefault("AWS_SECURITY_TOKEN", "test")
    os.environ.setdefault("AWS_SESSION_TOKEN", "test")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
