import pulumi
import pulumi_aws as aws

from infra_seedwork.constants import ObservabilityDefaults


def attach_bucket_lifecycle_configuration(
    name: str,
    bucket_id: pulumi.Input[str],
    noncurrent_version_expiration_days: int | None = None,
    abort_incomplete_multipart_upload_days: int = 1,
    expired_object_delete_marker: bool = True,
) -> aws.s3.BucketLifecycleConfigurationV2:
    """
    Attaches cost-saving S3 lifecycle rules to prune noncurrent versions,
    abort stalled multipart uploads, and remove expired object delete markers.
    """
    if noncurrent_version_expiration_days is None:
        noncurrent_version_expiration_days = (
            ObservabilityDefaults.DEFAULT_S3_NONCURRENT_RETENTION_DAYS
        )

    return aws.s3.BucketLifecycleConfigurationV2(
        f"{name}-lifecycle",
        bucket=bucket_id,
        rules=[
            aws.s3.BucketLifecycleConfigurationV2RuleArgs(
                id="cost-optimization-cleanup",
                status="Enabled",
                abort_incomplete_multipart_upload=aws.s3.BucketLifecycleConfigurationV2RuleAbortIncompleteMultipartUploadArgs(
                    days_after_initiation=abort_incomplete_multipart_upload_days,
                ),
                noncurrent_version_expiration=aws.s3.BucketLifecycleConfigurationV2RuleNoncurrentVersionExpirationArgs(
                    noncurrent_days=noncurrent_version_expiration_days,
                ),
                expiration=aws.s3.BucketLifecycleConfigurationV2RuleExpirationArgs(
                    expired_object_delete_marker=expired_object_delete_marker,
                )
                if expired_object_delete_marker
                else None,
            )
        ],
    )


def provision_secure_bucket(
    name: str,
    tags: dict,
    kms_key_arn: str = None,
    noncurrent_version_expiration_days: int | None = None,
) -> aws.s3.BucketV2:
    """
    Provisions a secure, versioned S3 bucket with public access blocked and cost lifecycle rules.
    Uses AWS KMS if provided, otherwise defaults to AES256.
    """
    if noncurrent_version_expiration_days is None:
        noncurrent_version_expiration_days = (
            ObservabilityDefaults.DEFAULT_S3_NONCURRENT_RETENTION_DAYS
        )

    bucket = aws.s3.BucketV2(
        name,
        bucket=name,
        tags=tags,
    )

    aws.s3.BucketPublicAccessBlock(
        f"{name}-pab",
        bucket=bucket.id,
        block_public_acls=True,
        block_public_policy=True,
        ignore_public_acls=True,
        restrict_public_buckets=True,
    )

    aws.s3.BucketVersioningV2(
        f"{name}-versioning",
        bucket=bucket.id,
        versioning_configuration=aws.s3.BucketVersioningV2VersioningConfigurationArgs(
            status="Enabled"
        ),
    )

    if noncurrent_version_expiration_days is not None:
        attach_bucket_lifecycle_configuration(
            name=name,
            bucket_id=bucket.id,
            noncurrent_version_expiration_days=noncurrent_version_expiration_days,
        )

    if kms_key_arn:
        aws.s3.BucketServerSideEncryptionConfigurationV2(
            f"{name}-sse",
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
    else:
        aws.s3.BucketServerSideEncryptionConfigurationV2(
            f"{name}-sse",
            bucket=bucket.id,
            rules=[
                aws.s3.BucketServerSideEncryptionConfigurationV2RuleArgs(
                    apply_server_side_encryption_by_default=aws.s3.BucketServerSideEncryptionConfigurationV2RuleApplyServerSideEncryptionByDefaultArgs(
                        sse_algorithm="AES256",
                    ),
                )
            ],
        )

    return bucket
