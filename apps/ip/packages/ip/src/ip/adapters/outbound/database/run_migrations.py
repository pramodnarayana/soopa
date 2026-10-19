"""Integration Platform database migration runner."""

from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from seedwork.infra.config import load_settings_safely
from seedwork.infra.config_models import PlatformDatabaseSettings

logger = structlog.get_logger(__name__)


def find_ip_ini_path() -> Path:
    """Locate alembic.ini for Integration Platform."""
    base_dir = Path(__file__).resolve().parent
    # 1. Search upwards
    current = base_dir
    for parent in [current, *list(current.parents)]:
        candidate = parent / "apps" / "ip" / "packages" / "ip" / "alembic.ini"
        if candidate.exists():
            return candidate.resolve()
        candidate = parent / "alembic.ini"
        if candidate.exists() and "ip" in str(candidate):
            return candidate.resolve()

    # 2. Check cwd
    cwd = Path.cwd()
    candidate = cwd / "apps" / "ip" / "packages" / "ip" / "alembic.ini"
    if candidate.exists():
        return candidate.resolve()

    raise FileNotFoundError("Could not locate alembic.ini for apps/ip/packages/ip")


def run_migrations() -> None:
    """Execute Integration Platform database migrations."""
    cwd = Path.cwd()
    if (cwd / ".env").exists():
        load_dotenv(cwd / ".env")
    else:
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / ".env").exists():
                load_dotenv(parent / ".env")
                break

    settings = load_settings_safely(PlatformDatabaseSettings)
    ini_path = find_ip_ini_path()
    script_location = str(Path(__file__).resolve().parent / "migrations")

    alembic_cfg = Config(str(ini_path))
    alembic_cfg.set_main_option("script_location", script_location)
    alembic_cfg.set_main_option("sqlalchemy.url", settings.global_url.replace("%", "%%"))

    logger.info("running_ip_migrations", script_location=script_location)
    command.upgrade(alembic_cfg, "head")
    logger.info("ip_migrations_completed")


if __name__ == "__main__":
    run_migrations()
