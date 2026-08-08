import argparse
import asyncio
import logging
import os
import re

import boto3
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

# Configure enterprise-grade logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ClearData")

DB_URLS = [
    os.environ.get("DB_URL", "postgresql+asyncpg://edi:edi_password@localhost:5432/edi_global"),
    os.environ.get(
        "DB_URL_SHARD_1", "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1"
    ),
]

TABLES_TO_CLEAR = ["edi_messages", "edi_json", "api_gateway", "outbox", "processed_events"]

# ---------------------------------------------------------------------------
# Safety guards
# ---------------------------------------------------------------------------

_LOCAL_HOST_PATTERN = re.compile(r"@(localhost|127\.\d+\.\d+\.\d+|::1)(:\d+)?/")
_LOCAL_ENDPOINT_PATTERN = re.compile(r"https?://(localhost|127\.\d+\.\d+\.\d+|::1)(:\d+)?")


def _assert_local_db_url(url: str) -> None:
    if not _LOCAL_HOST_PATTERN.search(url):
        raise SystemExit(
            f"SAFETY GUARD: Refusing to clear non-local database.\n"
            f"DB URL does not appear to target localhost: {url!r}"
        )


def _assert_local_aws_endpoint() -> str:
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
    if not _LOCAL_ENDPOINT_PATTERN.match(endpoint):
        raise SystemExit(
            f"SAFETY GUARD: Refusing to purge non-local SQS endpoint: {endpoint!r}\n"
            "Set AWS_ENDPOINT_URL to a localhost address (e.g. http://localhost:4566)."
        )
    return endpoint


# ---------------------------------------------------------------------------
# Core procedures
# ---------------------------------------------------------------------------


async def clear_database(db_url: str) -> None:
    logger.info(f"Connecting to database {db_url}...")
    try:
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            for table in TABLES_TO_CLEAR:
                try:
                    # Use a savepoint so a ProgrammingError rolls back only this
                    # table and allows the loop to continue for subsequent tables.
                    async with conn.begin_nested():
                        logger.info(f"Attempting to TRUNCATE public.{table} CASCADE...")
                        await conn.execute(text(f"TRUNCATE public.{table} CASCADE"))
                        logger.info(f"SUCCESS: Truncated public.{table}")
                except ProgrammingError as e:
                    logger.warning(
                        f"SKIPPED: Table public.{table} does not exist or cannot be truncated. {e}"
                    )
        logger.info(f"Finished database cleanup for {db_url}.")
    except Exception:
        logger.exception("CRITICAL ERROR clearing tables for %s", db_url)


def purge_sqs(endpoint_url: str) -> None:
    logger.info(f"Connecting to SQS at {endpoint_url}...")
    sqs = boto3.client(
        "sqs",
        endpoint_url=endpoint_url,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    queues = sqs.list_queues()
    if "QueueUrls" in queues:
        for q in queues["QueueUrls"]:
            try:
                sqs.purge_queue(QueueUrl=q)
                logger.info(f"SUCCESS: Purged SQS Queue -> {q}")
            except Exception:
                logger.exception("FAILED to purge %s", q)
    else:
        logger.warning("No SQS Queues found.")


async def main(i_am_sure: bool) -> None:
    if not i_am_sure:
        raise SystemExit(
            "SAFETY GUARD: This script permanently deletes data from all configured databases "
            "and SQS queues.\n"
            "Pass --i-am-sure to confirm you understand and accept this consequence."
        )

    # Validate all targets are local before touching anything.
    for db_url in DB_URLS:
        _assert_local_db_url(db_url)
    aws_endpoint = _assert_local_aws_endpoint()

    logger.info("=== STARTING DATA CLEAR PROCEDURE ===")
    for db_url in DB_URLS:
        await clear_database(db_url)
    purge_sqs(aws_endpoint)
    logger.info("=== DATA CLEAR PROCEDURE COMPLETED ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Clear all transactional data from local development databases and SQS queues."
    )
    parser.add_argument(
        "--i-am-sure",
        action="store_true",
        help="Explicit confirmation that you want to permanently delete data.",
    )
    args = parser.parse_args()
    asyncio.run(main(i_am_sure=args.i_am_sure))
