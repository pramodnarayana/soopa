import asyncio
import os
import urllib.parse

import boto3
from botocore.exceptions import ClientError
from database.provider import get_async_engine
from sqlalchemy import text

# Database Connection
DATABASE_URL = os.environ["DATABASE_URL"]

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
    engine = get_async_engine(DATABASE_URL)
    try:
        async with engine.begin() as conn:
            # Truncate all tables in a single statement for efficiency
            tables_list = ", ".join(TABLES_TO_TRUNCATE)
            await conn.execute(text(f"TRUNCATE TABLE {tables_list} CASCADE;"))
    finally:
        await engine.dispose()


def purge_sqs_queues() -> bool:
    sqs = boto3.client(
        "sqs",
        region_name=AWS_REGION,
        endpoint_url=AWS_ENDPOINT,
        aws_access_key_id="test",
        # Safe: dummy key for localstack
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    )

    failed = False
    for queue_name in QUEUES_TO_PURGE:
        try:
            queue_url = sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]
            sqs.purge_queue(QueueUrl=queue_url)
        except ClientError:
            failed = True
        except Exception:
            # Unexpected errors should propagate
            raise

    return not failed


async def main():

    # Safety guard: require local targets or explicit opt-in
    try:
        db_host = urllib.parse.urlparse(DATABASE_URL).hostname
    except ValueError:
        db_host = None

    try:
        sqs_host = urllib.parse.urlparse(AWS_ENDPOINT).hostname
    except ValueError:
        sqs_host = None

    db_is_local = db_host in ("localhost", "127.0.0.1")
    sqs_is_local = sqs_host in ("localhost", "127.0.0.1")
    explicit_override = os.getenv("ALLOW_DESTRUCTIVE_OPERATIONS", "").lower() == "true"

    if not ((db_is_local and sqs_is_local) or explicit_override):
        return

    success = purge_sqs_queues()
    if not success:
        return

    await truncate_database()


if __name__ == "__main__":
    asyncio.run(main())
