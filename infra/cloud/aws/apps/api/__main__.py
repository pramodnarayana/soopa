"""
Application Layer (Layer 3) - Unified API
"""

import json

import pulumi
import pulumi_aws as aws
from infra_seedwork import load_autoscaling_config_from_pulumi
from infra_seedwork.ecs import provision_fargate_service
from infra_seedwork.env import queue_env_vars_to_ecs_format
from infra_seedwork.messaging import build_database_pubsub_env_vars
from infra_seedwork.network import provision_target_group_and_rule
from infra_seedwork.topology import load_topology

_env = pulumi.get_stack()
_prefix = f"{_env}-api-"
_TAGS = {"ManagedBy": "pulumi", "Component": "api", "Environment": _env}

config = pulumi.Config()
edi_environment = config.get("edi_environment") or "T"
enabled_apps = config.get("enabled_apps") or "edi"
platform_admin_domains = (config.get("platform_admin_domains") or "").strip()
foundation_stack_ref = config.get("foundation_stack") or f"organization/foundation/{_env}"
platform_stack_ref = config.get("platform_stack") or f"organization/platform/{_env}"
data_stack_ref = config.get("data_stack") or f"organization/data/{_env}"
identity_stack_ref = config.get("identity_stack") or f"organization/casdoor/{_env}"
storage_stack_ref = config.get("storage_stack") or f"organization/edi-storage/{_env}"

foundation = pulumi.StackReference(foundation_stack_ref)
platform = pulumi.StackReference(platform_stack_ref)
obs_stack_ref = config.get("openobserve_stack") or f"organization/organization-openobserve/{_env}"
obs = pulumi.StackReference(obs_stack_ref)
data = pulumi.StackReference(data_stack_ref)
identity_stack = pulumi.StackReference(identity_stack_ref)
storage = pulumi.StackReference(storage_stack_ref)

pubsub_env_vars = build_database_pubsub_env_vars(load_topology())

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
namespace_name = platform.require_output("cloud_map_namespace_name")
app_defaults_secret_arn = platform.require_output("app_defaults_secret_arn")

edi_shard_db_endpoint = data.require_output("edi_shard_db_endpoint")
edi_shard_db_secret_arn = data.require_output("edi_shard_db_secret_arn")
global_db_endpoint = data.require_output("global_db_endpoint")
global_db_secret_arn = data.require_output("global_db_secret_arn")

identity_platform_realm = identity_stack.get_output("platform_realm").apply(
    lambda value: value or "soopa-platform"
)
identity_global_realm = identity_stack.get_output("global_realm").apply(
    lambda value: value or "soopa-global"
)
identity_admin_oauth_secret_arn = identity_stack.require_output("admin_oauth_secret_arn")

as2_payloads_bucket_name = storage.require_output("as2_payloads_bucket_name")
as2_payloads_bucket_arn = storage.require_output("as2_payloads_bucket_arn")

image_tag = config.get("image_tag") or "latest"
enable_observability = config.get_bool("enable_observability")
autoscaling_config = load_autoscaling_config_from_pulumi(config)
firelens_endpoint = obs.require_output("openobserve_endpoint") if enable_observability else None
obs_user_arn = obs.require_output("openobserve_user_secret_arn") if enable_observability else None
obs_pass_arn = (
    obs.require_output("openobserve_password_secret_arn") if enable_observability else None
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
        edi_shard_db_secret_arn,
        global_db_secret_arn,
        app_defaults_secret_arn,
        identity_admin_oauth_secret_arn,
        obs_user_arn,
        obs_pass_arn,
    ).apply(
        lambda args: json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["secretsmanager:GetSecretValue"],
                        "Resource": [arn for arn in args if arn],
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
    environment_vars=pulumi.Output.all(
        global_db=global_db_endpoint,
        edi_db=edi_shard_db_endpoint,
        domain=staging_domain,
        plat_realm=identity_platform_realm,
        glob_realm=identity_global_realm,
        s3_bucket=as2_payloads_bucket_name,
    ).apply(
        lambda args: [
            {"name": "ENV", "value": _env},
            {"name": "ENVIRONMENT", "value": _env},
            {"name": "ENABLED_APPS", "value": enabled_apps},
            {"name": "EDI_ENVIRONMENT", "value": edi_environment},
            {
                "name": "GLOBAL_DB_HOST",
                "value": args["global_db"][0]
                if isinstance(args["global_db"], tuple)
                else args["global_db"],
            },
            {
                "name": "EDI_DB_HOST",
                "value": args["edi_db"][0] if isinstance(args["edi_db"], tuple) else args["edi_db"],
            },
            {"name": "PUBLIC_BASE_URL", "value": f"https://api.{args['domain']}"},
            {"name": "AS2_RECEIVE_URL", "value": f"https://edi.{args['domain']}/as2/inbox"},
            {"name": "IDENTITY_PROVIDER", "value": "casdoor"},
            {"name": "IDENTITY_ISSUER", "value": f"https://identity.{args['domain']}"},
            {"name": "IDENTITY_API_URL", "value": f"https://identity.{args['domain']}"},
            {
                "name": "IDENTITY_JWKS_URL",
                "value": f"https://identity.{args['domain']}/.well-known/jwks",
            },
            {"name": "IDENTITY_PLATFORM_REALM", "value": args["plat_realm"]},
            {"name": "IDENTITY_GLOBAL_REALM", "value": args["glob_realm"]},
            {"name": "IDENTITY_PLATFORM_ORG_ID", "value": args["plat_realm"]},
            {
                "name": "IDENTITY_PLATFORM_ADMIN_DOMAINS",
                "value": platform_admin_domains or args["domain"],
            },
            {"name": "IDENTITY_SHARED_APP_REALM_DELIMITER", "value": "-org-"},
            {"name": "CORS_ALLOWED_ORIGINS", "value": f'["https://dashboard.{args["domain"]}"]'},
            {"name": "S3_BUCKET", "value": args["s3_bucket"]},
            *queue_env_vars_to_ecs_format(pubsub_env_vars, {}),
        ]
    ),
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
            "name": "DATABASE__SHARD_OVERRIDES__EDI_SHARD_1",
            "valueFrom": pulumi.Output.concat(edi_shard_db_secret_arn, ":async_url::"),
        },
        {
            "name": "IDENTITY_OAUTH_CLIENT_ID",
            "valueFrom": pulumi.Output.concat(
                identity_admin_oauth_secret_arn, ":dashboard_client_id::"
            ),
        },
        {
            "name": "IDENTITY_PLATFORM_ADMIN_CLIENT_ID",
            "valueFrom": pulumi.Output.concat(
                identity_admin_oauth_secret_arn, ":platform_admin_client_id::"
            ),
        },
        {
            "name": "IDENTITY_AUDIENCE",
            "valueFrom": pulumi.Output.concat(
                identity_admin_oauth_secret_arn, ":identity_audience::"
            ),
        },
        {
            "name": "CONFIG_SYNC_INTERNAL_TOKEN",
            "valueFrom": pulumi.Output.concat(
                app_defaults_secret_arn, ":config_sync_internal_token::"
            ),
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
        },
        {
            "Effect": "Allow",
            "Action": ["s3:GetObject"],
            "Resource": pulumi.Output.concat(as2_payloads_bucket_arn, "/*"),
        },
    ],
    autoscaling_config=autoscaling_config,
)

# Dedicated Control Plane Config Watch Gateway (xid8 Drain-Until-Empty Changelog Tailer).
# Intercepts `/api/v1/internal/*/config/*` at priority 190 (higher precedence than main API
# catch-all priority 500), keeping `unified-api` 100% pure stateless HTTP with $0 extra ALB cost.
config_watch_tg = provision_target_group_and_rule(
    name=f"{_prefix}watch",
    vpc_id=vpc_id,
    listener_arn=main_alb_listener_arn,
    priority=190,
    path_pattern="/api/v1/internal/*/config/*",
    host_header=pulumi.Output.concat("api.", staging_domain),
    port=8081,
    health_check_path="/health",
    deregistration_delay=30,
    tags=_TAGS,
)

config_watch_service = provision_fargate_service(
    name=f"{_prefix}config-watch-gateway",
    command=["uvicorn", "unified_api.watch_gateway:app", "--host", "0.0.0.0", "--port", "8081"],  # noqa: S104 - Fargate container must bind to all interfaces to receive ALB traffic
    cluster_arn=ecs_cluster_arn,
    execution_role_arn=execution_role.arn,
    ecr_image_uri=placeholder_image,
    subnets=private_subnets,
    security_group_id=app_sg_id,
    tags=_TAGS,
    firelens_endpoint=firelens_endpoint,
    obs_user_secret_arn=obs_user_arn,
    obs_password_secret_arn=obs_pass_arn,
    cpu="256",
    memory="512",
    port=8081,
    target_group_arn=config_watch_tg.arn,
    environment_vars=pulumi.Output.all(
        global_db=global_db_endpoint,
    ).apply(
        lambda args: [
            {"name": "ENV", "value": _env},
            {"name": "ENVIRONMENT", "value": _env},
            {"name": "ENABLED_APPS", "value": enabled_apps},
            {
                "name": "GLOBAL_DB_HOST",
                "value": args["global_db"][0]
                if isinstance(args["global_db"], tuple)
                else args["global_db"],
            },
        ]
    ),
    secrets=[
        {
            "name": "GLOBAL_DATABASE_URL",
            "valueFrom": pulumi.Output.concat(global_db_secret_arn, ":url::"),
        },
        {"name": "DATABASE_URL", "valueFrom": pulumi.Output.concat(global_db_secret_arn, ":url::")},
        {
            "name": "CONFIG_SYNC_INTERNAL_TOKEN",
            "valueFrom": pulumi.Output.concat(
                app_defaults_secret_arn, ":config_sync_internal_token::"
            ),
        },
    ],
    autoscaling_config=autoscaling_config,
)

# DNS Record moved to routing stack
pulumi.export("api_domain", pulumi.Output.concat("api.", staging_domain))
