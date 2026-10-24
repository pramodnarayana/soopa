"""
Integration Platform (IP) Control Plane & Data Plane Migration Runner
"""

import os

import structlog
from ip.engine.adapters.outbound.database.run_migrations import (
    run_migrations as run_ip_migrations,
)

logger = structlog.get_logger(__name__)


def run_ip_domain_migrations() -> None:
    """Execute global Control Plane and tenant shard Data Plane migrations for the IP bounded context."""
    logger.info(
        "ip_migrations_starting",
        ip_database_url_set=bool(os.environ.get("IP_DATABASE_URL")),
    )
    run_ip_migrations()
    logger.info("ip_migrations_completed")
