"""
Domain Data Seeding Runner (Isolated Bootstrap Tasks)
"""

import runpy
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


def find_repo_root() -> Path:
    """Find the root of the monorepo."""
    cwd = Path.cwd()
    if (cwd / "core").exists() and (cwd / "apps").exists():
        return cwd.resolve()

    current = Path(__file__).resolve()
    for parent in [current, *list(current.parents)]:
        if (parent / "core").exists() and (parent / "apps").exists():
            return parent.resolve()

    app_root = Path("/app")
    if (app_root / "core").exists():
        return app_root.resolve()

    raise FileNotFoundError("Could not locate monorepo root directory")


def execute_seed_script(script_relative_path: str) -> None:
    """Run an isolated seeding script using runpy."""
    repo_root = find_repo_root()
    target_path = repo_root / script_relative_path

    if not target_path.exists():
        raise FileNotFoundError(f"Seed script not found at path: {target_path}")

    logger.info("seed_script_started", script=script_relative_path)
    runpy.run_path(str(target_path), run_name="__main__")
    logger.info("seed_script_completed", script=script_relative_path)


def run_domain_seeds(domain: str) -> None:
    """Execute data seeding for a specific domain or all domains."""
    domain = domain.lower()
    logger.info("domain_seeding_started", domain=domain)

    if domain in ("ucp", "platform", "all"):
        execute_seed_script("core/ucp/packages/ucp/scripts/seed.py")
        execute_seed_script("core/ucp/apps/ucp-jobs-worker/scripts/seed_jobs.py")

    if domain in ("identity", "platform", "all"):
        execute_seed_script("core/platform/apps/identity-jobs-worker/scripts/seed_jobs.py")

    if domain in ("notification", "platform", "all"):
        execute_seed_script("core/platform/apps/notification-jobs-worker/scripts/seed_jobs.py")

    if domain in ("edi", "all"):
        execute_seed_script("apps/edi/scripts/seed_jobs.py")
        execute_seed_script("apps/edi/apps/edi-as2-server/scripts/seed.py")

    logger.info("domain_seeding_completed", domain=domain)
