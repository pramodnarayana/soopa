import boto3

sqs = boto3.client(
    "sqs",
    endpoint_url="http://localhost:4566",
    region_name="us-east-1",
    aws_access_key_id="test",
    # Safe: dummy key for localstack
    aws_secret_access_key="test",  # noqa: S106
)
queues = sqs.list_queues()
if "QueueUrls" in queues:
    for q in queues["QueueUrls"]:
        try:
            sqs.purge_queue(QueueUrl=q)
            print(f"Purged {q}")
        except Exception as e:  # noqa: BLE001
            print(f"Failed {q}: {e}")
