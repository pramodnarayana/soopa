"""
EDI Dataplane Migration Runner (edi_shard)
"""

import os

import structlog
from edi.adapters.outbound.database.run_migrations import run_migrations as run_edi_migrations

logger = structlog.get_logger(__name__)


def run_edi_domain_migrations() -> None:
    """Execute tenant shard migrations for the EDI bounded context."""
    logger.info(
        "edi_migrations_starting",
        edi_database_url_set=bool(os.environ.get("EDI_DATABASE_URL")),
    )
    run_edi_migrations()
    logger.info("edi_migrations_completed")
