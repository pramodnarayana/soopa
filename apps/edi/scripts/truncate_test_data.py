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
    async with engine.begin() as conn:
        for table in TABLES_TO_TRUNCATE:
            print(f"Truncating table {table}...")
            # We use CASCADE to handle foreign keys if any
            await conn.execute(text(f"TRUNCATE TABLE {table} CASCADE;"))
    await engine.dispose()
    print("Database tables truncated successfully.")


def purge_sqs_queues():
    print(f"Connecting to SQS at {AWS_ENDPOINT}")
    sqs = boto3.client(
        "sqs",
        region_name=AWS_REGION,
        endpoint_url=AWS_ENDPOINT,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )

    for queue_name in QUEUES_TO_PURGE:
        try:
            queue_url = sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]
            print(f"Purging queue {queue_name} ({queue_url})...")
            sqs.purge_queue(QueueUrl=queue_url)
        except Exception as e:
            print(f"Could not purge queue {queue_name}: {e}")
    print("SQS queues purged successfully.")


async def main():
    print("=== Truncating Test Data ===")
    purge_sqs_queues()
    await truncate_database()
    print("=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
