import json

import pulumi_aws as aws


def build_ecr_lifecycle_policy_doc(
    max_image_count: int = 10,
    untagged_retention_days: int = 1,
) -> str:
    """
    Builds an enterprise ECR Lifecycle Policy document in JSON.

    Pure function with zero cloud mocks needed.

    Rules:
    1. Untagged images are expired after `untagged_retention_days` (default 1 day).
    2. Any images beyond `max_image_count` (default 10) are expired.
    """
    if max_image_count < 1:
        raise ValueError(f"max_image_count must be at least 1, got {max_image_count}")
    if untagged_retention_days < 1:
        raise ValueError(
            f"untagged_retention_days must be at least 1, got {untagged_retention_days}"
        )

    policy = {
        "rules": [
            {
                "rulePriority": 1,
                "description": f"Expire untagged images older than {untagged_retention_days} day(s)",
                "selection": {
                    "tagStatus": "untagged",
                    "countType": "sinceImagePushed",
                    "countUnit": "days",
                    "countNumber": untagged_retention_days,
                },
                "action": {"type": "expire"},
            },
            {
                "rulePriority": 2,
                "description": f"Retain only the latest {max_image_count} images",
                "selection": {
                    "tagStatus": "any",
                    "countType": "imageCountMoreThan",
                    "countNumber": max_image_count,
                },
                "action": {"type": "expire"},
            },
        ]
    }
    return json.dumps(policy)


def attach_ecr_lifecycle_policy(
    name: str,
    repository: aws.ecr.Repository,
    max_image_count: int = 10,
    untagged_retention_days: int = 1,
) -> aws.ecr.LifecyclePolicy:
    """
    Provisions and attaches an AWS ECR Lifecycle Policy to an existing repository.
    """
    policy_doc = build_ecr_lifecycle_policy_doc(
        max_image_count=max_image_count,
        untagged_retention_days=untagged_retention_days,
    )

    return aws.ecr.LifecyclePolicy(
        f"{name}-lifecycle-policy",
        repository=repository.name,
        policy=policy_doc,
    )
