import pulumi
import pulumi_aws as aws


def provision_ecr(prefix: str, tags: dict):
    # ECR Repository for Zitadel Mirror
    zitadel_ecr_repo = aws.ecr.Repository(
        f"{prefix}zitadel-image",
        name=f"{prefix}zitadel-image",
        image_scanning_configuration=aws.ecr.RepositoryImageScanningConfigurationArgs(
            scan_on_push=True,
        ),
        force_delete=False,
        tags=tags,
        opts=pulumi.ResourceOptions(protect=True),
    )
    # ECR Repository for the Monorepo App
    app_ecr_repo = aws.ecr.Repository(
        f"{prefix}app-image",
        name=f"{prefix}app-image",
        image_scanning_configuration=aws.ecr.RepositoryImageScanningConfigurationArgs(
            scan_on_push=True,
        ),
        force_delete=False,
        tags=tags,
        opts=pulumi.ResourceOptions(protect=True),
    )
    # ECR Repository for OpenObserve Mirror
    openobserve_ecr_repo = aws.ecr.Repository(
        f"{prefix}openobserve-image",
        name=f"{prefix}openobserve-image",
        image_scanning_configuration=aws.ecr.RepositoryImageScanningConfigurationArgs(
            scan_on_push=True,
        ),
        force_delete=False,
        tags=tags,
        opts=pulumi.ResourceOptions(protect=True),
    )

    return zitadel_ecr_repo, app_ecr_repo, openobserve_ecr_repo
