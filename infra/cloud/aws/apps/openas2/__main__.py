"""
Application Layer - Testing: OpenAS2 Partner
=============================================
Provisions a standalone OpenAS2 ECS Fargate service for integration testing.
"""

import json

import pulumi
import pulumi_aws as aws
from infra_seedwork.ecs import provision_fargate_service
from infra_seedwork.network import provision_target_group_and_rule

_env = pulumi.get_stack()
_prefix = f"{_env}-"
_TAGS = {"ManagedBy": "pulumi", "Component": "openas2", "Environment": _env}

config = pulumi.Config()
foundation_stack_ref = config.get("foundation_stack") or f"organization/foundation/{_env}"
platform_stack_ref = config.get("platform_stack") or f"organization/platform/{_env}"
desired_count = config.get_int("desired_count")

if desired_count is None:
    desired_count = 1

foundation = pulumi.StackReference(foundation_stack_ref)
platform = pulumi.StackReference(platform_stack_ref)

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
obs_endpoint = pulumi.Output.concat("openobserve.", namespace_name, ":5080")
obs_user_arn = platform.require_output("openobserve_user_secret_arn")
obs_pass_arn = platform.require_output("openobserve_password_secret_arn")

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
# but the old default matcher "200-499" excluded 411. Accept the full range.
tg_arn = provision_target_group_and_rule(
    name=f"{_prefix}openas2",
    vpc_id=vpc_id,
    port=10080,
    health_check_path="/",
    health_check_matcher="200-499,411",
    listener_arn=main_alb_listener_arn,
    path_pattern="/*",
    host_header=pulumi.Output.concat("openas2.", staging_domain),
    priority=60,
    tags=_TAGS,
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
    firelens_endpoint=obs_endpoint,
    obs_user_secret_arn=obs_user_arn,
    obs_password_secret_arn=obs_pass_arn,
    enable_execute_command=True,
    tags=_TAGS,
)

# ── Exports ───────────────────────────────────────────────────────────────────
pulumi.export("openas2_ecr_repository_url", ecr_repo.repository_url)
pulumi.export("openas2_url", pulumi.Output.concat("https://openas2.", staging_domain, "/as2/inbox"))
