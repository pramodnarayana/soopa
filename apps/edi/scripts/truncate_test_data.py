import asyncio
import os

import boto3
from database.provider import get_async_engine
from sqlalchemy import text

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
    engine = get_async_engine(DATABASE_URL)
    try:
        async with engine.begin() as conn:
            # Truncate all tables in a single statement for efficiency
            tables_list = ", ".join(TABLES_TO_TRUNCATE)
            print(f"Truncating tables: {tables_list}")
            await conn.execute(text(f"TRUNCATE TABLE {tables_list} CASCADE;"))
        print("Database tables truncated successfully.")
    finally:
        await engine.dispose()


def purge_sqs_queues() -> bool:
    print(f"Connecting to SQS at {AWS_ENDPOINT}")
    sqs = boto3.client(
        "sqs",
        region_name=AWS_REGION,
        endpoint_url=AWS_ENDPOINT,
        aws_access_key_id="test",
        # Safe: dummy key for localstack
        aws_secret_access_key="test",  # noqa: S106
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
        except Exception:
            # Unexpected errors should propagate
            raise

    if failed:
        print("ERROR: Some SQS queues failed to purge.")
        return False
    else:
        print("SQS queues purged successfully.")
        return True


async def main():
    print("=== Truncating Test Data ===")

    import urllib.parse

    # Safety guard: require local targets or explicit opt-in
    try:
        db_host = urllib.parse.urlparse(DATABASE_URL).hostname
    except Exception:  # noqa: BLE001
        db_host = None

    try:
        sqs_host = urllib.parse.urlparse(AWS_ENDPOINT).hostname
    except Exception:  # noqa: BLE001
        sqs_host = None

    db_is_local = db_host in ("localhost", "127.0.0.1")
    sqs_is_local = sqs_host in ("localhost", "127.0.0.1")
    explicit_override = os.getenv("ALLOW_DESTRUCTIVE_OPERATIONS", "").lower() == "true"

    if not ((db_is_local and sqs_is_local) or explicit_override):
        print("ERROR: Refusing to run destructive operations on non-local targets.")
        print(f"  Database: {DATABASE_URL}")
        print(f"  SQS Endpoint: {AWS_ENDPOINT}")
        print("  Set ALLOW_DESTRUCTIVE_OPERATIONS=true to override this safety check.")
        return

    success = purge_sqs_queues()
    if not success:
        print("ERROR: Aborting truncate due to SQS purge failure.")
        return

    await truncate_database()
    print("=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
