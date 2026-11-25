"""Clears transactional EDI tables across local development PostgreSQL shards."""

from __future__ import annotations

import argparse
import asyncio
import os
import re

import structlog
from database.provider import get_async_engine
from database.router import DatabaseRouter
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

logger = structlog.get_logger("ClearData")

global_url = os.environ["DATABASE_URL"]

TABLES_TO_CLEAR = [
    "edi_messages",
    "edi_json",
    "api_gateway",
    "outbox",
    "events_processed",
    "trace_events",
    "ack_receipts",
]

_LOCAL_HOST_PATTERN = re.compile(r"@(localhost|127\.\d+\.\d+\.\d+|::1)(:\d+)?/")


def _assert_local_db_url(url: str) -> None:
    if not _LOCAL_HOST_PATTERN.search(url):
        raise SystemExit(
            f"SAFETY GUARD: Refusing to clear non-local database.\n"
            f"DB URL does not appear to target localhost: {url!r}"
        )


async def clear_database(db_url: str) -> None:
    logger.info("clear_database_starting", db_url=db_url)
    engine = get_async_engine(db_url)
    try:
        async with engine.begin() as conn:
            for table in TABLES_TO_CLEAR:
                try:
                    async with conn.begin_nested():
                        await conn.execute(text(f"TRUNCATE public.{table} CASCADE"))
                        logger.info("table_truncated", table=table)
                except ProgrammingError as exc:
                    logger.info("table_truncate_skipped", table=table, reason=str(exc))
        logger.info("clear_database_completed", db_url=db_url)
    except Exception:
        logger.exception("clear_database_failed", db_url=db_url)
        raise
    finally:
        await engine.dispose()


async def main(i_am_sure: bool) -> None:
    if not i_am_sure:
        raise SystemExit(
            "SAFETY GUARD: This script permanently deletes transactional data from local EDI databases.\n"
            "Pass --i-am-sure to confirm."
        )

    _assert_local_db_url(global_url)
    router = DatabaseRouter(global_db_url=global_url)
    shards = await router.get_all_shards(app_slug="edi")
    await router.close_all()

    db_urls = [shard[1].replace("@edi_postgres_shard:5432", "@localhost:5433") for shard in shards]
    for db_url in db_urls:
        _assert_local_db_url(db_url)

    logger.info("clear_data_procedure_started", shard_count=len(db_urls))
    for db_url in db_urls:
        await clear_database(db_url)
    logger.info("clear_data_procedure_completed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Clear transactional data from local development EDI databases."
    )
    parser.add_argument(
        "--i-am-sure",
        action="store_true",
        help="Explicit confirmation that you want to permanently delete data.",
    )
    args = parser.parse_args()
    asyncio.run(main(i_am_sure=args.i_am_sure))
