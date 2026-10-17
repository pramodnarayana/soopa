import pulumi
from infra_seedwork.storage import provision_secure_bucket

_env = pulumi.get_stack()
_prefix = f"{_env}-edi-"
_TAGS = {"ManagedBy": "pulumi", "Component": "edi-storage", "Environment": _env}

config = pulumi.Config()
# Payloads bucket with automatic cost lifecycle pruning
payloads_bucket = provision_secure_bucket(
    name=f"{_prefix}as2-payloads",
    tags=_TAGS,
    noncurrent_version_expiration_days=config.get_int("noncurrent_version_retention_days"),
)


pulumi.export("as2_payloads_bucket_name", payloads_bucket.bucket)
pulumi.export("as2_payloads_bucket_arn", payloads_bucket.arn)
