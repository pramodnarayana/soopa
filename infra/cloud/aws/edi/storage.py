"""
EDI Storage Infrastructure
===========================

Provisions the S3 buckets used by the EDI platform for payload storage.

Design decisions
----------------
- Versioning is enabled on all buckets so payloads can be recovered after
  accidental deletion without relying on database backups.
- Public access is blocked at the bucket level in all environments.
- Server-side encryption (SSE-S3) is enabled by default. For production,
  override with SSE-KMS via stack config.
"""

import pulumi
import pulumi_aws as aws


class EdiStorageStack:
    """Composes all S3 storage resources for the EDI bounded context."""

    def __init__(self) -> None:
        self.edi_payloads = self._make_edi_payloads_bucket()

    def _make_edi_payloads_bucket(self) -> aws.s3.BucketV2:
        config = pulumi.Config("edi-platform")
        kms_key_arn = config.require("kms_key_arn")

        bucket = aws.s3.BucketV2(
            "edi-payloads",
            tags={"ManagedBy": "pulumi", "Component": "edi"},
        )

        # Block all public access
        aws.s3.BucketPublicAccessBlock(
            "edi-payloads-public-access-block",
            bucket=bucket.id,
            block_public_acls=True,
            block_public_policy=True,
            ignore_public_acls=True,
            restrict_public_buckets=True,
        )

        # Enable versioning for payload recovery
        aws.s3.BucketVersioningV2(
            "edi-payloads-versioning",
            bucket=bucket.id,
            versioning_configuration=aws.s3.BucketVersioningV2VersioningConfigurationArgs(
                status="Enabled"
            ),
        )

        # Enable server-side encryption (Strict Enterprise: KMS required)
        aws.s3.BucketServerSideEncryptionConfigurationV2(
            "edi-payloads-sse",
            bucket=bucket.id,
            rules=[
                aws.s3.BucketServerSideEncryptionConfigurationV2RuleArgs(
                    apply_server_side_encryption_by_default=aws.s3.BucketServerSideEncryptionConfigurationV2RuleApplyServerSideEncryptionByDefaultArgs(
                        sse_algorithm="aws:kms",
                        kms_master_key_id=kms_key_arn,
                    ),
                    bucket_key_enabled=True,
                )
            ],
        )

        return bucket
