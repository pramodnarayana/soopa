import argparse
import asyncio
import os
import re

import boto3
import structlog
from database.provider import get_async_engine
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

logger = structlog.get_logger("ClearData")

from database.router import DatabaseRouter

global_url = os.environ["DATABASE_URL"]

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
    logger.info("Connecting to database {db_url}...", db_url=db_url)
    try:
        engine = get_async_engine(db_url)
        async with engine.begin() as conn:
            for table in TABLES_TO_CLEAR:
                try:
                    # Use a savepoint so a ProgrammingError rolls back only this
                    # table and allows the loop to continue for subsequent tables.
                    async with conn.begin_nested():
                        logger.info("Attempting to TRUNCATE public.{table} CASCADE...", table=table)
                        await conn.execute(text(f"TRUNCATE public.{table} CASCADE"))
                        logger.info("SUCCESS: Truncated public.{table}", table=table)
                except ProgrammingError as e:
                    logger.warning(
                        "SKIPPED: Table public.{table} does not exist or cannot be truncated. {e}",
                        table=table,
                        e=e,
                    )
        logger.info("Finished database cleanup for {db_url}.", db_url=db_url)
    except Exception:
        logger.exception("CRITICAL ERROR clearing tables for %s", db_url)


def purge_sqs(endpoint_url: str) -> None:
    logger.info("Connecting to SQS at {endpoint_url}...", endpoint_url=endpoint_url)
    sqs = boto3.client(
        "sqs",
        endpoint_url=endpoint_url,
        region_name="us-east-1",
        aws_access_key_id="test",
        # Safe: dummy key for localstack
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    )
    queues = sqs.list_queues()
    if "QueueUrls" in queues:
        for q in queues["QueueUrls"]:
            try:
                sqs.purge_queue(QueueUrl=q)
                logger.info("SUCCESS: Purged SQS Queue -> {q}", q=q)
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

    router = DatabaseRouter(global_db_url=global_url)
    shards = await router.get_all_shards()
    await router.close_all()

    db_urls = [global_url] + [shard[1] for shard in shards]

    # Validate all targets are local before touching anything.
    for db_url in db_urls:
        _assert_local_db_url(db_url)
    aws_endpoint = _assert_local_aws_endpoint()

    logger.info("=== STARTING DATA CLEAR PROCEDURE ===")
    for db_url in db_urls:
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
