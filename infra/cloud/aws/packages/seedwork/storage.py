import pulumi_aws as aws


def provision_secure_bucket(name: str, tags: dict, kms_key_arn: str = None) -> aws.s3.BucketV2:
    """
    Provisions a secure, versioned S3 bucket with public access blocked.
    Uses AWS KMS if provided, otherwise defaults to AES256.
    """
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
