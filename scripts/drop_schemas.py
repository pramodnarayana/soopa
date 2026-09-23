#!/usr/bin/env python3
import asyncio
import os
import sys

import asyncpg
import structlog
from dotenv import load_dotenv

# Load root .env to get database credentials if not exported
load_dotenv()

logger = structlog.get_logger()


async def drop_public_schema(dsn: str, db_name: str):
    logger.info("Dropping 'public' schema", db_name=db_name)
    try:
        conn = await asyncpg.connect(dsn)
        await conn.execute("DROP SCHEMA IF EXISTS public CASCADE;")
        await conn.execute("CREATE SCHEMA public;")
        # Re-grant standard permissions if necessary
        await conn.execute("GRANT ALL ON SCHEMA public TO public;")
        await conn.close()
        logger.info("Reset 'public' schema", db_name=db_name)
    except (asyncpg.Error, OSError) as e:
        logger.exception("Failed to reset", db_name=db_name, error=str(e))
        sys.exit(1)


async def main():
    global_url = os.getenv("DATABASE_URL")
    if not global_url:
        logger.error("DATABASE_URL is not set.")
        sys.exit(1)

    logger.info("Initiating fast local database reset (schemas only)...")

    # 1. Drop Global Schema
    await drop_public_schema(global_url, "Global DB")

    # 2. Drop EDI Schema
    # Since this is purely for local dev test resets, we use the local docker exposed port (5433).
    edi_dsn = "postgresql://edi:edi_password@localhost:5433/edi_shard_1"
    await drop_public_schema(edi_dsn, "EDI Shard 1")

    logger.info("Local databases are perfectly clean. Ready for db:migrate!")


if __name__ == "__main__":
    asyncio.run(main())
