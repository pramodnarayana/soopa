import pulumi
import pulumi_aws as aws
from infra_seedwork import ObservabilityDefaults
from infra_seedwork.ecr import attach_ecr_lifecycle_policy


def provision_ecr(prefix: str, tags: dict):
    config = pulumi.Config()
    configured_max = config.get_int("ecr_max_image_count")
    max_images = (
        configured_max
        if configured_max is not None
        else ObservabilityDefaults.DEFAULT_ECR_MAX_IMAGE_COUNT
    )

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
    attach_ecr_lifecycle_policy(
        f"{prefix}zitadel-image",
        zitadel_ecr_repo,
        max_image_count=max_images,
        untagged_retention_days=1,
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
    attach_ecr_lifecycle_policy(
        f"{prefix}app-image",
        app_ecr_repo,
        max_image_count=max_images,
        untagged_retention_days=1,
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
    attach_ecr_lifecycle_policy(
        f"{prefix}openobserve-image",
        openobserve_ecr_repo,
        max_image_count=max_images,
        untagged_retention_days=1,
    )

    return zitadel_ecr_repo, app_ecr_repo, openobserve_ecr_repo
