import pulumi
import pulumi_aws as aws
from seedwork.storage import provision_secure_bucket


def provision_storage(prefix: str, tags: dict) -> aws.s3.BucketV2:
    config = pulumi.Config("edi")
    kms_key_arn = config.get("kms_key_arn")

    return provision_secure_bucket(f"{prefix}payloads", tags, kms_key_arn)
