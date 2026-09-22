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
