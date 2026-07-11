import boto3

sqs = boto3.client(
    "sqs",
    endpoint_url="http://localhost:4566",
    region_name="us-east-1",
    aws_access_key_id="test",
    aws_secret_access_key="test",
)
queues = sqs.list_queues()
if "QueueUrls" in queues:
    for q in queues["QueueUrls"]:
        try:
            sqs.purge_queue(QueueUrl=q)
            print(f"Purged {q}")
        except Exception as e:
            print(f"Failed {q}: {e}")
