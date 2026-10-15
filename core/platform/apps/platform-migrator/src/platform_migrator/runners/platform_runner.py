"""
Platform / Control Plane Database Migration Runner (global_db)
"""

import os
from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config

logger = structlog.get_logger(__name__)


def find_platform_alembic_ini() -> Path:
    """Locate the platform database alembic.ini file."""
    # Check current working directory first
    cwd = Path.cwd()
    candidate = cwd / "core" / "platform" / "packages" / "database" / "alembic.ini"
    if candidate.exists():
        return candidate.resolve()

    # Search upwards from current file location
    current = Path(__file__).resolve()
    for parent in [current, *list(current.parents)]:
        candidate = parent / "core" / "platform" / "packages" / "database" / "alembic.ini"
        if candidate.exists():
            return candidate.resolve()
        candidate = parent / "database" / "alembic.ini"
        if candidate.exists():
            return candidate.resolve()

    # Container fallback (/app)
    app_candidate = Path("/app/core/platform/packages/database/alembic.ini")
    if app_candidate.exists():
        return app_candidate.resolve()

    raise FileNotFoundError(
        "Could not locate platform database alembic.ini. "
        "Ensure core/platform/packages/database is present."
    )


def run_platform_domain_migrations() -> None:
    """Execute Alembic migrations for the Platform / Control Plane database."""
    alembic_ini_path = find_platform_alembic_ini()
    logger.info(
        "platform_migrations_starting",
        alembic_ini=str(alembic_ini_path),
        database_url_set=bool(
            os.environ.get("DATABASE_URL") or os.environ.get("GLOBAL_DATABASE_URL")
        ),
    )

    alembic_cfg = Config(str(alembic_ini_path))
    # Ensure script_location is absolute to avoid relative path resolution bugs
    alembic_cfg.set_main_option("script_location", str(alembic_ini_path.parent / "migrations"))

    command.upgrade(alembic_cfg, "head")
    logger.info("platform_migrations_completed", alembic_ini=str(alembic_ini_path))
