import asyncio
import os

import boto3
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Database Connection
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/soopa_data_plane"
)

# SQS Connection (LocalStack)
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
AWS_ENDPOINT = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")

QUEUES_TO_PURGE = [
    "edi-transform-orchestration-dev",
    "edi-delivery-orchestration-dev",
    "edi-outbox-events-dev",
]

TABLES_TO_TRUNCATE = ["outbox", "processed_events", "edi_messages", "edi_json", "audit_log", "jobs"]


async def truncate_database():
    print(f"Connecting to database: {DATABASE_URL}")
    engine = create_async_engine(DATABASE_URL, echo=False)
    try:
        async with engine.begin() as conn:
            # Truncate all tables in a single statement for efficiency
            tables_list = ", ".join(TABLES_TO_TRUNCATE)
            print(f"Truncating tables: {tables_list}")
            await conn.execute(text(f"TRUNCATE TABLE {tables_list} CASCADE;"))
        print("Database tables truncated successfully.")
    finally:
        await engine.dispose()


def purge_sqs_queues():
    print(f"Connecting to SQS at {AWS_ENDPOINT}")
    sqs = boto3.client(
        "sqs",
        region_name=AWS_REGION,
        endpoint_url=AWS_ENDPOINT,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )

    from botocore.exceptions import ClientError

    failed = False
    for queue_name in QUEUES_TO_PURGE:
        try:
            queue_url = sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]
            print(f"Purging queue {queue_name} ({queue_url})...")
            sqs.purge_queue(QueueUrl=queue_url)
        except ClientError as e:
            print(f"Could not purge queue {queue_name}: {e}")
            failed = True
        except Exception as e:
            # Unexpected errors should propagate
            raise

    if failed:
        print("WARNING: Some SQS queues failed to purge.")
    else:
        print("SQS queues purged successfully.")


async def main():
    print("=== Truncating Test Data ===")

    # Safety guard: require local targets or explicit opt-in
    db_is_local = "localhost" in DATABASE_URL or "127.0.0.1" in DATABASE_URL
    sqs_is_local = "localhost" in AWS_ENDPOINT or "127.0.0.1" in AWS_ENDPOINT
    explicit_override = os.getenv("ALLOW_DESTRUCTIVE_OPERATIONS", "").lower() == "true"

    if not ((db_is_local and sqs_is_local) or explicit_override):
        print("ERROR: Refusing to run destructive operations on non-local targets.")
        print(f"  Database: {DATABASE_URL}")
        print(f"  SQS Endpoint: {AWS_ENDPOINT}")
        print("  Set ALLOW_DESTRUCTIVE_OPERATIONS=true to override this safety check.")
        return

    purge_sqs_queues()
    await truncate_database()
    print("=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
