"""Truncates local EDI transactional test tables in PostgreSQL."""

from __future__ import annotations

import asyncio
import os
import urllib.parse

from database.provider import get_async_engine
from sqlalchemy import text

DATABASE_URL = os.environ["DATABASE_URL"]
TABLES_TO_TRUNCATE = ["outbox", "event_idempotency", "edi_messages", "edi_json", "jobs"]


async def truncate_database() -> None:
    engine = get_async_engine(DATABASE_URL)
    try:
        async with engine.begin() as conn:
            tables_list = ", ".join(TABLES_TO_TRUNCATE)
            await conn.execute(text(f"TRUNCATE TABLE {tables_list} CASCADE;"))
    finally:
        await engine.dispose()


async def main() -> None:
    try:
        db_host = urllib.parse.urlparse(DATABASE_URL).hostname
    except ValueError:
        db_host = None

    db_is_local = db_host in ("localhost", "127.0.0.1")
    explicit_override = os.getenv("ALLOW_DESTRUCTIVE_OPERATIONS", "").lower() == "true"
    if not (db_is_local or explicit_override):
        return

    await truncate_database()


if __name__ == "__main__":
    asyncio.run(main())
