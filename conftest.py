import os

import pytest


@pytest.fixture(autouse=True)
def _enforce_unit_test_isolation(request):
    """
    Enterprise Standard: Unit tests must NEVER connect to the database.
    If a test is not explicitly marked with @pytest.mark.integration,
    we scramble the DATABASE_URL to guarantee it crashes if it tries to connect.
    """
    if "integration" not in [m.name for m in request.node.iter_markers()]:
        # Save original
        original = os.environ.get("DATABASE_URL")
        # Scramble it
        os.environ["DATABASE_URL"] = "postgresql+asyncpg://blocked:blocked@localhost:0/blocked"

        yield

        # Restore
        if original is not None:
            os.environ["DATABASE_URL"] = original
        else:
            del os.environ["DATABASE_URL"]
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
