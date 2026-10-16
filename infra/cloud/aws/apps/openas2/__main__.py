"""
Application Layer - Testing: OpenAS2 Partner
=============================================
Provisions a standalone OpenAS2 ECS Fargate service for integration testing.
"""

import json

import pulumi
import pulumi_aws as aws
from infra_seedwork import ObservabilityDefaults, StackEnvironment
from infra_seedwork.ecr import attach_ecr_lifecycle_policy
from infra_seedwork.ecs import provision_fargate_service
from infra_seedwork.network import provision_target_group_and_rule

_env = pulumi.get_stack()
_prefix = f"{_env}-"
_TAGS = {"ManagedBy": "pulumi", "Component": "openas2", "Environment": _env}

config = pulumi.Config()
if _env == StackEnvironment.PRODUCTION:
    raise ValueError("OpenAS2 testing infrastructure cannot be deployed to production.")
foundation_stack_ref = config.get("foundation_stack") or f"organization/foundation/{_env}"
platform_stack_ref = config.get("platform_stack") or f"organization/platform/{_env}"
obs_stack_ref = config.get("openobserve_stack") or f"organization/organization-openobserve/{_env}"
desired_count = config.get_int("desired_count")

if desired_count is None:
    desired_count = 1  # Active during working hours; powered down at night via schedule

foundation = pulumi.StackReference(foundation_stack_ref)
platform = pulumi.StackReference(platform_stack_ref)
obs = pulumi.StackReference(obs_stack_ref)

vpc_id = foundation.require_output("vpc_id")
private_subnets = [
    foundation.require_output("private_subnet_a_id"),
    foundation.require_output("private_subnet_b_id"),
]
app_sg_id = foundation.require_output("app_sg_id")

ecs_cluster_arn = platform.require_output("ecs_cluster_arn")
main_alb_listener_arn = platform.require_output("main_alb_listener_arn")
staging_domain = platform.require_output("staging_domain")
namespace_name = platform.require_output("cloud_map_namespace_name")
obs_endpoint = obs.require_output("openobserve_endpoint")
obs_user_arn = obs.require_output("openobserve_user_secret_arn")
obs_pass_arn = obs.require_output("openobserve_password_secret_arn")

image_tag = config.get("image_tag") or "latest"

_region = aws.get_region()

# ── ECR Repository ────────────────────────────────────────────────────────────
# The OpenAS2 requires a custom image with embedded Java/XML configs.
ecr_repo = aws.ecr.Repository(
    f"{_prefix}openas2",
    name=f"{_prefix}openas2",
    image_tag_mutability="MUTABLE",
    force_delete=True,
    tags=_TAGS,
)
configured_max_images = config.get_int("max_image_count")
max_image_count = (
    configured_max_images
    if configured_max_images is not None
    else ObservabilityDefaults.DEFAULT_ECR_MAX_IMAGE_COUNT
)

attach_ecr_lifecycle_policy(
    f"{_prefix}openas2",
    ecr_repo,
    max_image_count=max_image_count,
    untagged_retention_days=1,
)
ecr_image_uri = pulumi.Output.concat(ecr_repo.repository_url, f":{image_tag}")


# ── Execution Role ────────────────────────────────────────────────────────────
execution_role = aws.iam.Role(
    f"{_prefix}openas2-ecs-execution-role",
    assume_role_policy=json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }
    ),
    tags=_TAGS,
)
aws.iam.RolePolicyAttachment(
    f"{_prefix}openas2-ecs-exec-role-attach",
    role=execution_role.name,
    policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
)
aws.iam.RolePolicy(
    f"{_prefix}openas2-ecs-exec-secrets-policy",
    role=execution_role.id,
    policy=pulumi.Output.all(obs_user_arn, obs_pass_arn).apply(
        lambda args: json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": "secretsmanager:GetSecretValue",
                        "Resource": [args[0], args[1]],
                    },
                    {
                        "Effect": "Allow",
                        "Action": "logs:CreateLogGroup",
                        "Resource": "*",
                    },
                ],
            }
        )
    ),
)

# ── Target Group & ALB Rule ───────────────────────────────────────────────────
# OpenAS2 returns HTTP 411 (Length Required) on plain GET / — it IS responding,
# and the 200-499 range natively includes 411.
tg_arn = provision_target_group_and_rule(
    name=f"{_prefix}openas2",
    vpc_id=vpc_id,
    port=10080,
    health_check_path="/",
    health_check_matcher="200-499",
    listener_arn=main_alb_listener_arn,
    path_pattern="/*",
    host_header=pulumi.Output.concat("openas2.", staging_domain),
    priority=60,
    tags=_TAGS,
)

# ── S3 Outbox Bucket (Sidecar) ────────────────────────────────────────────────
# Strictly bind the bucket name to the environment to prevent global collisions
target_bucket_name = f"openas2-flowwolf-{_env}-outbox"

outbox_bucket = aws.s3.BucketV2(
    f"{_prefix}openas2-outbox",
    bucket=target_bucket_name,
    force_destroy=True,
    tags=_TAGS,
)

# Cost optimization: Expire test transit objects after 1 day
aws.s3.BucketLifecycleConfigurationV2(
    f"{_prefix}openas2-outbox-lifecycle",
    bucket=outbox_bucket.id,
    rules=[
        aws.s3.BucketLifecycleConfigurationV2RuleArgs(
            id="expire-test-payloads",
            status="Enabled",
            expiration=aws.s3.BucketLifecycleConfigurationV2RuleExpirationArgs(
                days=1,
            ),
        )
    ],
)

# ── ECS Service ───────────────────────────────────────────────────────────────
# The OpenAS2 container needs the FLOWWOLF_AS2_URL injected so the entrypoint
# can template the partnerships.xml with the correct AWS inbound URL.
flowwolf_as2_url = pulumi.Output.concat("https://edi.", staging_domain, "/as2/inbox")

fargate_service = provision_fargate_service(
    name=f"{_prefix}openas2",
    cluster_arn=ecs_cluster_arn,
    ecr_image_uri=ecr_image_uri,
    command=[],
    port=10080,
    target_group_arn=tg_arn,
    subnets=private_subnets,
    security_group_id=app_sg_id,
    execution_role_arn=execution_role.arn,
    desired_count=desired_count,
    cpu="512",
    memory="1024",
    environment_vars=[
        {"name": "FLOWWOLF_AS2_URL", "value": flowwolf_as2_url},
    ],
    bucket_arns=[outbox_bucket.arn, outbox_bucket.arn.apply(lambda arn: f"{arn}/*")],
    volumes=[{"name": "outbox-volume"}],
    app_mount_points=[
        {
            "sourceVolume": "outbox-volume",
            "containerPath": f"/opt/openas2/data/outbox/FLOWWOLF_{_env.upper()}_AS2",
            "readOnly": False,
        }
    ],
    sidecar_container={
        "name": "s3-poller",
        "image": "amazon/aws-cli:2.15.11",
        "entryPoint": ["sh", "-c"],
        "command": [
            f"mkdir -p /opt/openas2/data/outbox/FLOWWOLF_{_env.upper()}_AS2/.staging && while true; do "
            f"if aws s3 mv s3://{target_bucket_name} /opt/openas2/data/outbox/FLOWWOLF_{_env.upper()}_AS2/.staging --recursive; then "
            f"for f in /opt/openas2/data/outbox/FLOWWOLF_{_env.upper()}_AS2/.staging/*; do "
            f'[ -e "$f" ] && (mv "$f" /opt/openas2/data/outbox/FLOWWOLF_{_env.upper()}_AS2/ || echo "Failed to move $f" >&2); '
            f"done; "
            f"fi; "
            f"sleep 30; done",
        ],
        "essential": False,
        "mountPoints": [
            {
                "sourceVolume": "outbox-volume",
                "containerPath": f"/opt/openas2/data/outbox/FLOWWOLF_{_env.upper()}_AS2",
                "readOnly": False,
            }
        ],
    },
    firelens_endpoint=obs_endpoint,
    obs_user_secret_arn=obs_user_arn,
    obs_password_secret_arn=obs_pass_arn,
    enable_execute_command=True,
    use_spot=config.get_bool("use_spot") if config.get_bool("use_spot") is not None else True,
    tags=_TAGS,
)


# ── Exports ───────────────────────────────────────────────────────────────────
pulumi.export("openas2_ecr_repository_url", ecr_repo.repository_url)
pulumi.export("openas2_url", pulumi.Output.concat("https://openas2.", staging_domain, "/as2/inbox"))
