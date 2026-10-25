"""
Command Line Interface for Platform Migrations and Domain Seeding
"""

import argparse
import sys

import structlog
from dotenv import load_dotenv

from platform_migrator.runners.platform_runner import run_platform_domain_migrations
from platform_migrator.runners.seed_runner import run_domain_seeds

load_dotenv()

logger = structlog.get_logger(__name__)


def handle_migrate(domain: str = "platform") -> None:
    """Handle database schema migrations for the platform Control Plane (global_db)."""
    domain = domain.lower()
    logger.info("migration_command_received", domain=domain)

    if domain == "platform":
        run_platform_domain_migrations()
    else:
        logger.error("invalid_migration_domain", domain=domain)
        raise ValueError(
            f"Unknown migration domain '{domain}'. Valid options for platform-migrator: platform."
        )

    logger.info("migration_command_completed", domain=domain)


def handle_seed(domain: str) -> None:
    """Handle data seeding for a target domain."""
    domain = domain.lower()
    logger.info("seed_command_received", domain=domain)
    run_domain_seeds(domain)
    logger.info("seed_command_completed", domain=domain)


def main() -> None:
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
        default="all",
        choices=["ucp", "identity", "notification", "edi", "all"],
        help="Domain scope to seed",
    )

    args = parser.parse_args()

    try:
        if args.action == "migrate":
            handle_migrate(args.domain)
        elif args.action == "seed":
            handle_seed(args.domain)
        else:
            parser.print_help()
            sys.exit(1)
    except Exception as exc:
        logger.exception("platform_migrator_failed", action=args.action, error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
