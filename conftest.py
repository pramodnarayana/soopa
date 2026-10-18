import os

import pytest
from dotenv import load_dotenv

load_dotenv()


BLOCKED_CLOUD_ENV_KEYS = [
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_CONFIG_FILE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SECURITY_TOKEN",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
]


@pytest.fixture(autouse=True)
def _enforce_unit_test_isolation(request):
    """
    Enterprise Standard: Unit tests must NEVER connect to the database or external cloud infrastructure.
    If a test is not explicitly marked with @pytest.mark.integration:
    1. We scramble the DATABASE_URL to guarantee it crashes if it tries to connect.
    2. We sandbox cloud provider configuration (e.g. AWS) to prevent ambient developer credentials
       from leaking into unit test runs, ensuring 100% parity with clean CI environments.
    """
    if "integration" not in [m.name for m in request.node.iter_markers()]:
        # Save original state
        original_db = os.environ.get("DATABASE_URL")
        saved_cloud_env = {key: os.environ.get(key) for key in BLOCKED_CLOUD_ENV_KEYS}

        # Scramble Database
        os.environ["DATABASE_URL"] = "postgresql+asyncpg://blocked:blocked@localhost:0/blocked"

        # Neutralize Cloud Credentials (hermetic isolation)
        os.environ["AWS_SHARED_CREDENTIALS_FILE"] = os.devnull
        os.environ["AWS_CONFIG_FILE"] = os.devnull
        for key in [
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SECURITY_TOKEN",
            "AWS_SESSION_TOKEN",
            "AWS_PROFILE",
        ]:
            os.environ.pop(key, None)

        yield

        # Restore Database
        if original_db is not None:
            os.environ["DATABASE_URL"] = original_db
        else:
            os.environ.pop("DATABASE_URL", None)

        # Restore Cloud Environment
        for key, val in saved_cloud_env.items():
            if val is not None:
                os.environ[key] = val
            else:
                os.environ.pop(key, None)
    else:
        yield


def pytest_sessionfinish(session, exitstatus):
    """
    Enterprise Standard: Do not fail the build if a package has zero tests collected
    (e.g., when a package only has integration tests but the unit test phase runs).
    Pytest returns 5 when no tests are collected. We gracefully downgrade 5 to 0.
    """
    if exitstatus == 5:
        session.exitstatus = 0
