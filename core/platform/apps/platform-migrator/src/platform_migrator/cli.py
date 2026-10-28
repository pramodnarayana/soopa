"""
Command Line Interface for Platform Migrations and Domain Seeding
"""

import argparse
import sys
from collections.abc import Callable, Sequence

import structlog
from dotenv import load_dotenv

from platform_migrator.runners.platform_runner import run_platform_domain_migrations
from platform_migrator.runners.seed_runner import run_domain_seeds

load_dotenv()

logger = structlog.get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build and configure the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="platform-migrator",
        description="Enterprise Programmatic Database Migration & Seeding CLI",
    )
    subparsers = parser.add_subparsers(dest="action", required=True, help="Action to execute")

    # migrate subparser
    migrate_parser = subparsers.add_parser(
        "migrate", help="Execute platform database schema migrations"
    )
    migrate_parser.add_argument(
        "--domain",
        type=str,
        default="platform",
        choices=["platform"],
        help="Domain scope to migrate (platform = global_db Control Plane migrations)",
    )

    # seed subparser
    seed_parser = subparsers.add_parser(
        "seed", help="Execute domain data seeding (Environment bootstrap only)"
    )
    seed_parser.add_argument(
        "--domain",
        type=str,
        default="platform",
        choices=["platform", "ucp", "identity", "notification", "edi", "ip", "all"],
        help="Domain scope to seed",
    )
    return parser


def handle_migrate(
    domain: str = "platform",
    migration_runner: Callable[[], None] = run_platform_domain_migrations,
) -> None:
    """Handle database schema migrations for the platform Control Plane (global_db)."""
    domain = domain.lower()
    logger.info("migration_command_received", domain=domain)

    if domain == "platform":
        migration_runner()
    else:
        logger.error("invalid_migration_domain", domain=domain)
        raise ValueError(
            f"Unknown migration domain '{domain}'. Valid options for platform-migrator: platform."
        )

    logger.info("migration_command_completed", domain=domain)


def handle_seed(
    domain: str,
    seed_runner: Callable[[str], None] = run_domain_seeds,
) -> None:
    """Handle data seeding for a target domain."""
    domain = domain.lower()
    logger.info("seed_command_received", domain=domain)
    seed_runner(domain)
    logger.info("seed_command_completed", domain=domain)


def main(
    args: Sequence[str] | None = None,
    migration_runner: Callable[[], None] = run_platform_domain_migrations,
    seed_runner: Callable[[str], None] = run_domain_seeds,
) -> int:
    """CLI Entrypoint with full Inversion of Control."""
    parser = build_parser()
    parsed_args = parser.parse_args(args)

    try:
        if parsed_args.action == "migrate":
            handle_migrate(parsed_args.domain, migration_runner=migration_runner)
        elif parsed_args.action == "seed":
            handle_seed(parsed_args.domain, seed_runner=seed_runner)
        else:
            parser.print_help()
            return 1
        return 0
    except Exception as exc:
        logger.exception("platform_migrator_failed", action=parsed_args.action, error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
