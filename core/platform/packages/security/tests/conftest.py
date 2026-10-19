"""Enterprise Hermetic Unit Test Isolation for Security Package."""

import os

import pytest

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
def _enforce_security_unit_test_isolation(request: pytest.FixtureRequest):
    """Enterprise Standard: Unit tests must NEVER connect to external cloud infrastructure.

    If a test is not explicitly marked with @pytest.mark.integration:
    1. We sandbox cloud provider configuration (e.g. AWS) to prevent ambient developer credentials
       from leaking into unit test runs, guaranteeing 100% parity with clean CI environments.
    """
    if "integration" not in [m.name for m in request.node.iter_markers()]:
        saved_cloud_env = {key: os.environ.get(key) for key in BLOCKED_CLOUD_ENV_KEYS}

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

        for key, val in saved_cloud_env.items():
            if val is not None:
                os.environ[key] = val
            else:
                os.environ.pop(key, None)
    else:
        yield
