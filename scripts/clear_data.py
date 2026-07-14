import asyncio
import logging
import os

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


async def clear_database(db_url):
    logger.info(f"Connecting to database {db_url}...")
    try:
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            for table in TABLES_TO_CLEAR:
                try:
                    logger.info(f"Attempting to TRUNCATE public.{table} CASCADE...")
                    await conn.execute(text(f"TRUNCATE public.{table} CASCADE"))
                    logger.info(f"SUCCESS: Truncated public.{table}")
                except ProgrammingError as e:
                    logger.warning(
                        f"SKIPPED: Table public.{table} does not exist or cannot be truncated. {e}"
                    )
        logger.info(f"Finished database cleanup for {db_url}.")
    except Exception as e:
        logger.error(f"CRITICAL ERROR clearing tables for {db_url}: {e}")


def purge_sqs():
    logger.info("Connecting to LocalStack SQS...")
    endpoint_url = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
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
            except Exception as e:
                logger.error(f"FAILED to purge {q}: {e}")
    else:
        logger.warning("No SQS Queues found in LocalStack.")


async def main():
    logger.info("=== STARTING DATA CLEAR PROCEDURE ===")
    for db_url in DB_URLS:
        await clear_database(db_url)
    purge_sqs()
    logger.info("=== DATA CLEAR PROCEDURE COMPLETED ===")


if __name__ == "__main__":
    asyncio.run(main())
