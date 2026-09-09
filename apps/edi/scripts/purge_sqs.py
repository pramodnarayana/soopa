import os

import boto3
from botocore.exceptions import ClientError

sqs = boto3.client(
    "sqs",
    endpoint_url="http://localhost:4566",
    region_name="us-east-1",
    aws_access_key_id="test",
    # Safe: dummy key for localstack
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
)
queues = sqs.list_queues()
failed_purges: list[tuple[str, str]] = []
if "QueueUrls" in queues:
    for q in queues["QueueUrls"]:
        try:
            sqs.purge_queue(QueueUrl=q)
        except ClientError as exc:
            failed_purges.append((q, str(exc)))

if failed_purges:
    failure_details = "; ".join(f"{queue}: {error}" for queue, error in failed_purges)
    raise SystemExit(f"Failed to purge {len(failed_purges)} SQS queue(s): {failure_details}")
