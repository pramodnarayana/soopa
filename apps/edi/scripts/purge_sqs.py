import contextlib
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
if "QueueUrls" in queues:
    for q in queues["QueueUrls"]:
        with contextlib.suppress(ClientError):
            sqs.purge_queue(QueueUrl=q)
