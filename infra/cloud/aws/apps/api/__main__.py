"""
Application Layer (Layer 3) - Unified API
"""

import json

import pulumi
import pulumi_aws as aws
from infra_seedwork.ecs import provision_fargate_service
from infra_seedwork.network import provision_target_group_and_rule

_env = pulumi.get_stack()
_prefix = f"{_env}-api-"
_TAGS = {"ManagedBy": "pulumi", "Component": "api", "Environment": _env}

config = pulumi.Config()
foundation_stack_ref = config.get("foundation_stack") or f"organization/foundation/{_env}"
platform_stack_ref = config.get("platform_stack") or f"organization/platform/{_env}"
data_stack_ref = config.get("data_stack") or f"organization/data/{_env}"
zitadel_stack_ref = config.get("zitadel_stack") or f"organization/zitadel-infrastructure/{_env}"

foundation = pulumi.StackReference(foundation_stack_ref)
platform = pulumi.StackReference(platform_stack_ref)
data = pulumi.StackReference(data_stack_ref)
zitadel = pulumi.StackReference(zitadel_stack_ref)

vpc_id = foundation.require_output("vpc_id")
private_subnets = [
    foundation.require_output("private_subnet_a_id"),
    foundation.require_output("private_subnet_b_id"),
]
app_sg_id = foundation.require_output("app_sg_id")

ecs_cluster_arn = platform.require_output("ecs_cluster_arn")
ecr_repository_url = platform.require_output("ecr_repository_url")
main_alb_listener_arn = platform.require_output("main_alb_listener_arn")
staging_domain = platform.require_output("staging_domain")

edi_shard_db_endpoint = data.require_output("edi_shard_db_endpoint")
edi_shard_db_secret_arn = data.require_output("edi_shard_db_secret_arn")
global_db_endpoint = data.require_output("global_db_endpoint")
global_db_secret_arn = data.require_output("global_db_secret_arn")

image_tag = config.get("image_tag") or "latest"
enable_observability = config.get_bool("enable_observability")
firelens_endpoint = (
    platform.require_output("openobserve_endpoint") if enable_observability else None
)
obs_user_arn = (
    platform.require_output("openobserve_user_secret_arn") if enable_observability else None
)
obs_pass_arn = (
    platform.require_output("openobserve_password_secret_arn") if enable_observability else None
)
placeholder_image = pulumi.Output.concat(ecr_repository_url, f":{image_tag}")

execution_role = aws.iam.Role(
    f"{_prefix}ecs-execution-role",
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

aws.iam.RolePolicy(
    f"{_prefix}ecs-exec-role-secrets-policy",
    role=execution_role.id,
    policy=pulumi.Output.all(
        edi_shard_db_secret_arn, global_db_secret_arn, obs_user_arn, obs_pass_arn
    ).apply(
        lambda args: json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["secretsmanager:GetSecretValue"],
                        "Resource": [args[0], args[1], args[2], args[3]],
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["logs:CreateLogGroup"],
                        "Resource": "*",
                    },
                ],
            }
        )
    ),
)
aws.iam.RolePolicyAttachment(
    f"{_prefix}ecs-exec-role-attach",
    role=execution_role.name,
    policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
)

# API routes to /* (catch all) but we'll use priority 500 (lower priority than EDI /as2/*)
api_tg = provision_target_group_and_rule(
    name=f"{_prefix}main",
    vpc_id=vpc_id,
    listener_arn=main_alb_listener_arn,
    priority=500,
    path_pattern="/*",
    tags=_TAGS,
)

api_service = provision_fargate_service(
    name=f"{_prefix}server",
    command=["uvicorn", "unified_api.main:app", "--host", "0.0.0.0", "--port", "8000"],  # noqa: S104 - Fargate container must bind to all interfaces to receive ALB traffic
    cluster_arn=ecs_cluster_arn,
    execution_role_arn=execution_role.arn,
    ecr_image_uri=placeholder_image,
    subnets=private_subnets,
    security_group_id=app_sg_id,
    tags=_TAGS,
    firelens_endpoint=firelens_endpoint,
    obs_user_secret_arn=obs_user_arn,
    obs_password_secret_arn=obs_pass_arn,
    port=8000,
    target_group_arn=api_tg.arn,
    environment_vars=[
        {"name": "ENVIRONMENT", "value": "staging"},
        {
            "name": "GLOBAL_DB_HOST",
            "value": pulumi.Output.all(global_db_endpoint).apply(lambda args: args[0]),
        },
        {
            "name": "EDI_DB_HOST",
            "value": pulumi.Output.all(edi_shard_db_endpoint).apply(lambda args: args[0]),
        },
        {"name": "PUBLIC_BASE_URL", "value": pulumi.Output.concat("https://api.", staging_domain)},
        {
            "name": "IDENTITY_ISSUER",
            "value": pulumi.Output.concat("https://identity.", staging_domain),
        },
        {
            "name": "IDENTITY_UCP_PROJECT_ID",
            "value": zitadel.require_output("ucp_project_id"),
        },
        {
            "name": "IDENTITY_OAUTH_CLIENT_ID",
            "value": zitadel.require_output("ucp_web_client_id"),
        },
        {
            "name": "IDENTITY_PLATFORM_ORG_ID",
            "value": zitadel.require_output("platform_org_id"),
        },
        {
            "name": "IDENTITY_API_URL",
            "value": pulumi.Output.concat("https://identity.", staging_domain),
        },
        {
            "name": "CORS_ALLOWED_ORIGINS",
            "value": staging_domain.apply(lambda d: f'["https://dashboard.{d}"]'),
        },
    ],
    secrets=[
        {
            "name": "GLOBAL_DATABASE_URL",
            "valueFrom": pulumi.Output.concat(global_db_secret_arn, ":url::"),
        },
        {"name": "DATABASE_URL", "valueFrom": pulumi.Output.concat(global_db_secret_arn, ":url::")},
        {
            "name": "EDI_DATABASE_URL",
            "valueFrom": pulumi.Output.concat(edi_shard_db_secret_arn, ":url::"),
        },
        {
            "name": "SHARD_OVERRIDES__EDI_SHARD_1",
            "valueFrom": pulumi.Output.concat(edi_shard_db_secret_arn, ":async_url::"),
        },
    ],
    extra_task_policy_statements=[
        {
            "Effect": "Allow",
            "Action": [
                "secretsmanager:CreateSecret",
                "secretsmanager:GetSecretValue",
                "secretsmanager:PutSecretValue",
                "secretsmanager:DescribeSecret",
                "secretsmanager:DeleteSecret",
                "secretsmanager:UpdateSecret",
            ],
            "Resource": pulumi.Output.concat(
                "arn:aws:secretsmanager:",
                aws.get_region().name,
                ":",
                aws.get_caller_identity().account_id,
                ":secret:edi/as2_key/*",
            ),
        }
    ],
)

# ── DNS Record ────────────────────────────────────────────────────────────────
hosted_zone = aws.route53.get_zone_output(name=staging_domain)
main_alb_dns_name = platform.require_output("main_alb_dns_name")
main_alb_zone_id = platform.require_output("main_alb_zone_id")

api_dns_record = aws.route53.Record(
    f"{_prefix}api-dns",
    zone_id=hosted_zone.id,
    name=pulumi.Output.concat("api.", staging_domain),
    type="A",
    aliases=[
        aws.route53.RecordAliasArgs(
            name=main_alb_dns_name,
            zone_id=main_alb_zone_id,
            evaluate_target_health=False,
        )
    ],
)

pulumi.export("api_domain", api_dns_record.name)
