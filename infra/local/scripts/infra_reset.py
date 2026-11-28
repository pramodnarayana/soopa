#!/usr/bin/env python3
"""Local database schema reset helper (IdP reset is handled by infra/local/identity/bootstrap.py)."""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg
import structlog
from dotenv import load_dotenv

load_dotenv()

logger = structlog.get_logger(__name__)


async def drop_public_schema(dsn: str, db_name: str) -> None:
    logger.info("dropping_public_schema", db_name=db_name)
    try:
        conn = await asyncpg.connect(dsn)
        try:
            slots = await conn.fetch("SELECT slot_name FROM pg_replication_slots")
            for slot in slots:
                slot_name = slot["slot_name"]
                logger.info("dropping_replication_slot", slot_name=slot_name)
                await conn.execute("SELECT pg_drop_replication_slot($1);", slot_name)
        except asyncpg.Error as exc:
            logger.error("replication_slot_drop_failed", error=str(exc))

        await conn.execute("DROP SCHEMA IF EXISTS public CASCADE;")
        await conn.execute("CREATE SCHEMA public;")
        await conn.execute("GRANT ALL ON SCHEMA public TO public;")
        await conn.close()
        logger.info("public_schema_reset", db_name=db_name)
    except (asyncpg.Error, OSError) as exc:
        logger.exception("database_reset_failed", db_name=db_name, error=str(exc))
        sys.exit(1)


async def main() -> None:
    logger.info("infra_reset_started")

    global_url = os.getenv("DATABASE_URL")
    if not global_url:
        logger.error("database_url_missing")
        sys.exit(1)

    edi_dsn = os.getenv(
        "EDI_DATABASE_URL", "postgresql://edi:edi_password@localhost:5433/edi_shard"
    )

    await drop_public_schema(global_url, "Global DB")
    await drop_public_schema(edi_dsn, "EDI Shard 1")

    logger.info("infra_reset_complete")


if __name__ == "__main__":
    asyncio.run(main())
