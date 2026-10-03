import pulumi

_env = pulumi.get_stack()
_prefix = f"{_env}-edi-"
_TAGS = {"ManagedBy": "pulumi", "Component": "edi-storage", "Environment": _env}

from infra_seedwork.storage import provision_secure_bucket

# Payloads bucket
payloads_bucket = provision_secure_bucket(
    name=f"{_prefix}as2-payloads",
    tags=_TAGS,
)

# (Lifecycle config removed for simplicity)

pulumi.export("as2_payloads_bucket_name", payloads_bucket.bucket)
pulumi.export("as2_payloads_bucket_arn", payloads_bucket.arn)
