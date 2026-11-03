from collections.abc import Mapping

import pulumi
import pulumi_aws as aws

from infra_seedwork.constants import ObservabilityDefaults, S3Constants


def build_account_scoped_bucket_name(logical_name: str, account_id: str) -> str:
    """
    Deterministically scopes a logical S3 bucket name to an AWS Account ID
    (`<logical_name>-<account_id>`) to prevent global S3 namespace collisions.
    """
    normalized_name = logical_name.strip()
    normalized_account = account_id.strip()
    if not normalized_name:
        raise ValueError("S3 logical_name must be a non-empty string.")
    if not normalized_account or not normalized_account.isdigit():
        raise ValueError(f"AWS account_id must be numeric, got '{account_id}'.")

    suffix = f"-{normalized_account}"
    scoped_name = (
        normalized_name if normalized_name.endswith(suffix) else f"{normalized_name}{suffix}"
    )
    if not (
        S3Constants.MIN_BUCKET_NAME_LENGTH <= len(scoped_name) <= S3Constants.MAX_BUCKET_NAME_LENGTH
    ):
        raise ValueError(
            f"Scoped S3 bucket name '{scoped_name}' length ({len(scoped_name)}) "
            f"must be between {S3Constants.MIN_BUCKET_NAME_LENGTH} and "
            f"{S3Constants.MAX_BUCKET_NAME_LENGTH} characters."
        )
    return scoped_name


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
                id=S3Constants.LIFECYCLE_RULE_ID,
                status=S3Constants.STATUS_ENABLED,
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
    tags: Mapping[str, pulumi.Input[str]],
    kms_key_arn: pulumi.Input[str] | None = None,
    noncurrent_version_expiration_days: int | None = None,
    bucket_name: pulumi.Input[str] | None = None,
) -> aws.s3.BucketV2:
    """
    Provisions a secure, versioned S3 bucket with public access blocked and cost lifecycle rules.
    Defaults physical bucket name to `<name>-<account_id>` to guarantee global S3 uniqueness.
    Uses AWS KMS if provided, otherwise defaults to AES256.
    """
    if noncurrent_version_expiration_days is None:
        noncurrent_version_expiration_days = (
            ObservabilityDefaults.DEFAULT_S3_NONCURRENT_RETENTION_DAYS
        )

    resolved_bucket_name: pulumi.Input[str] = (
        bucket_name
        if bucket_name is not None
        else pulumi.Output.from_input(aws.get_caller_identity().account_id).apply(
            lambda acc_id: build_account_scoped_bucket_name(name, str(acc_id))
        )
    )

    bucket = aws.s3.BucketV2(
        name,
        bucket=resolved_bucket_name,
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
            status=S3Constants.STATUS_ENABLED
        ),
    )

    attach_bucket_lifecycle_configuration(
        name=name,
        bucket_id=bucket.id,
        noncurrent_version_expiration_days=noncurrent_version_expiration_days,
    )

    if kms_key_arn is not None:
        aws.s3.BucketServerSideEncryptionConfigurationV2(
            f"{name}-sse",
            bucket=bucket.id,
            rules=[
                aws.s3.BucketServerSideEncryptionConfigurationV2RuleArgs(
                    apply_server_side_encryption_by_default=aws.s3.BucketServerSideEncryptionConfigurationV2RuleApplyServerSideEncryptionByDefaultArgs(
                        sse_algorithm=S3Constants.SSE_AWS_KMS,
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
                        sse_algorithm=S3Constants.SSE_AES256,
                    ),
                )
            ],
        )

    return bucket
