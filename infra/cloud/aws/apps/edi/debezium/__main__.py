"""
Application Layer (Layer 3) - EDI Bounded Context: Debezium CDC
================================================================
Provisions only the Debezium CDC Server ECS Fargate service.

Tier 5: Deployed when DEBEZIUM_VERSION changes in versions.env.
Depends on: edi/messaging (topic ARNs), platform (cluster, ECR), data (DB).
"""

import json
import os

import pulumi
import pulumi_aws as aws
from dotenv import load_dotenv
from infra_seedwork.ecs import provision_fargate_service

_env = pulumi.get_stack()
_prefix = f"{_env}-edi-"
_TAGS = {"ManagedBy": "pulumi", "Component": "edi-debezium", "Environment": _env}

# ── Resolve Debezium version from versions.env ────────────────────────────────
_workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../../"))
load_dotenv(os.path.join(_workspace_root, "versions.env"))
_debezium_version = os.environ["DEBEZIUM_VERSION"]

# ── Stack References ──────────────────────────────────────────────────────────
config = pulumi.Config()
foundation_stack_ref = config.get("foundation_stack") or f"organization/foundation/{_env}"
platform_stack_ref = config.get("platform_stack") or f"organization/platform/{_env}"
data_stack_ref = config.get("data_stack") or f"organization/data/{_env}"
messaging_stack_ref = config.get("messaging_stack") or f"organization/edi-messaging/{_env}"

foundation = pulumi.StackReference(foundation_stack_ref)
platform = pulumi.StackReference(platform_stack_ref)
data = pulumi.StackReference(data_stack_ref)
messaging = pulumi.StackReference(messaging_stack_ref)

private_subnets = [
    foundation.require_output("private_subnet_a_id"),
    foundation.require_output("private_subnet_b_id"),
]
app_sg_id = foundation.require_output("app_sg_id")

ecs_cluster_arn = platform.require_output("ecs_cluster_arn")
debezium_ecr_repo_url = platform.require_output("debezium_ecr_repo_url")
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

edi_shard_db_endpoint = data.require_output("edi_shard_db_endpoint")
edi_shard_db_secret_arn = data.require_output("edi_shard_db_secret_arn")

# Fetch the data-plane topic ARN from the messaging stack
data_plane_topic_arn = messaging.require_output("sns_edi_data_plane_topic_arn")

_region = aws.get_region()
_identity = aws.get_caller_identity()

debezium_image_uri = pulumi.Output.concat(debezium_ecr_repo_url, f":{_debezium_version}")

# ── Execution Role ────────────────────────────────────────────────────────────
execution_role = aws.iam.Role(
    f"{_prefix}debezium-ecs-execution-role",
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
    f"{_prefix}debezium-ecs-exec-role-attach",
    role=execution_role.name,
    policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
)
aws.iam.RolePolicy(
    f"{_prefix}debezium-ecs-exec-role-policy",
    role=execution_role.id,
    policy=pulumi.Output.all(edi_shard_db_secret_arn, obs_user_arn, obs_pass_arn).apply(
        lambda args: json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["secretsmanager:GetSecretValue"],
                        "Resource": [args[0], args[1], args[2]],
                    },
                    {"Effect": "Allow", "Action": ["logs:CreateLogGroup"], "Resource": "*"},
                ],
            }
        )
    ),
)

# ── Debezium CDC Service ──────────────────────────────────────────────────────
debezium_server = provision_fargate_service(
    name=f"{_prefix}debezium-server",
    command=[],
    cluster_arn=ecs_cluster_arn,
    execution_role_arn=execution_role.arn,
    ecr_image_uri=debezium_image_uri,
    subnets=private_subnets,
    security_group_id=app_sg_id,
    tags=_TAGS,
    extra_task_policy_statements=[
        {"Effect": "Allow", "Action": ["sns:Publish"], "Resource": data_plane_topic_arn}
    ],
    firelens_endpoint=firelens_endpoint,
    obs_user_secret_arn=obs_user_arn,
    obs_password_secret_arn=obs_pass_arn,
    environment_vars=[
        {"name": "AWS_REGION", "value": _region.name},
        {"name": "DEBEZIUM_SINK_SNS_REGION", "value": _region.name},
        {"name": "DEBEZIUM_SINK_TYPE", "value": "sns"},
        {"name": "DEBEZIUM_SINK_SNS_TOPIC_ARN", "value": data_plane_topic_arn},
        {
            "name": "DEBEZIUM_SOURCE_DATABASE_HOSTNAME",
            "value": pulumi.Output.all(edi_shard_db_endpoint).apply(
                lambda args: args[0].split(":")[0]
            ),
        },
        {
            "name": "DEBEZIUM_SOURCE_CONNECTOR_CLASS",
            "value": "io.debezium.connector.postgresql.PostgresConnector",
        },
        {"name": "DEBEZIUM_SOURCE_DATABASE_DBNAME", "value": "edi_shard"},
        {"name": "DEBEZIUM_SOURCE_TOPIC_PREFIX", "value": "edi_shard_events"},
        {"name": "DEBEZIUM_SOURCE_PLUGIN_NAME", "value": "pgoutput"},
        {
            "name": "DEBEZIUM_SOURCE_OFFSET_STORAGE",
            "value": "io.debezium.storage.jdbc.offset.JdbcOffsetBackingStore",
        },
        {
            "name": "DEBEZIUM_SOURCE_OFFSET_STORAGE_JDBC_URL",
            "value": pulumi.Output.all(edi_shard_db_endpoint).apply(
                lambda args: f"jdbc:postgresql://{args[0]}/edi_shard"
            ),
        },
        {
            "name": "DEBEZIUM_SOURCE_MAX_BATCH_SIZE",
            "value": "10",
        },
    ],
    secrets=[
        {
            "name": "DEBEZIUM_SOURCE_DATABASE_USER",
            "valueFrom": pulumi.Output.concat(edi_shard_db_secret_arn, ":username::"),
        },
        {
            "name": "DEBEZIUM_SOURCE_DATABASE_PASSWORD",
            "valueFrom": pulumi.Output.concat(edi_shard_db_secret_arn, ":password::"),
        },
        {
            "name": "DEBEZIUM_SOURCE_OFFSET_STORAGE_JDBC_USER",
            "valueFrom": pulumi.Output.concat(edi_shard_db_secret_arn, ":username::"),
        },
        {
            "name": "DEBEZIUM_SOURCE_OFFSET_STORAGE_JDBC_PASSWORD",
            "valueFrom": pulumi.Output.concat(edi_shard_db_secret_arn, ":password::"),
        },
    ],
)
