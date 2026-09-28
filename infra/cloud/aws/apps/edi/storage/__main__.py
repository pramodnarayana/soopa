import pulumi
import pulumi_aws as aws

_env = pulumi.get_stack()
_prefix = f"{_env}-edi-"
_TAGS = {"ManagedBy": "pulumi", "Component": "edi-storage", "Environment": _env}

# Payloads bucket
payloads_bucket = aws.s3.Bucket(
    f"{_prefix}as2-payloads",
    bucket=f"{_prefix}as2-payloads",
    force_destroy=True,
    tags=_TAGS,
)

# (Lifecycle config removed for simplicity)

pulumi.export("as2_payloads_bucket_name", payloads_bucket.bucket)
pulumi.export("as2_payloads_bucket_arn", payloads_bucket.arn)
