import pulumi_aws as aws


def provision_ecr(prefix: str, tags: dict):
    # ECR Repository for Zitadel Mirror
    zitadel_ecr_repo = aws.ecr.Repository(
        f"{prefix}zitadel-image",
        name=f"{prefix}zitadel-image",
        image_scanning_configuration=aws.ecr.RepositoryImageScanningConfigurationArgs(
            scan_on_push=True,
        ),
        force_delete=True,
        tags=tags,
    )
    # ECR Repository for the Monorepo App
    app_ecr_repo = aws.ecr.Repository(
        f"{prefix}app-image",
        name=f"{prefix}app-image",
        image_scanning_configuration=aws.ecr.RepositoryImageScanningConfigurationArgs(
            scan_on_push=True,
        ),
        force_delete=True,
        tags=tags,
    )

    # ECR Repository for Debezium Mirror
    debezium_ecr_repo = aws.ecr.Repository(
        f"{prefix}debezium-mirror",
        name=f"{prefix}debezium-mirror",
        image_scanning_configuration=aws.ecr.RepositoryImageScanningConfigurationArgs(
            scan_on_push=True,
        ),
        force_delete=True,
        tags=tags,
    )

    return zitadel_ecr_repo, app_ecr_repo, debezium_ecr_repo
