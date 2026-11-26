"""
Platform Layer (Control Plane) - Database Migrator & Seeder
===========================================================
Provisions the dedicated ECS Task Definition used by the CI/CD pipeline
(Release Phase) to run Alembic database migrations and bootstrap seeding
for the Platform Control Plane (global_db).
"""

import json

import pulumi
import pulumi_aws as aws
from infra_seedwork.messaging import build_database_pubsub_env_vars
from infra_seedwork.topology import load_topology

_env = pulumi.get_stack()
_prefix = f"{_env}-platform-migrator-"
_TAGS = {"ManagedBy": "pulumi", "Component": "platform-migrator", "Environment": _env}

# ── Stack References ──────────────────────────────────────────────────────────
config = pulumi.Config()
foundation_stack_ref = config.get("foundation_stack") or f"organization/foundation/{_env}"
platform_stack_ref = config.get("platform_stack") or f"organization/platform/{_env}"
data_stack_ref = config.get("data_stack") or f"organization/data/{_env}"
identity_stack_ref = config.get("identity_stack") or f"organization/casdoor/{_env}"

foundation = pulumi.StackReference(foundation_stack_ref)
platform = pulumi.StackReference(platform_stack_ref)
data = pulumi.StackReference(data_stack_ref)
identity_stack = pulumi.StackReference(identity_stack_ref)

pubsub_env_vars = build_database_pubsub_env_vars(
    load_topology(),
    queue_filter={"identity-jobs", "notification-jobs", "ucp-jobs"},
    topic_filter=set(),
)

# ── Infrastructure Inputs ─────────────────────────────────────────────────────
private_subnets = [
    foundation.require_output("private_subnet_a_id"),
    foundation.require_output("private_subnet_b_id"),
]
app_sg_id = foundation.require_output("app_sg_id")

ecr_repository_url = platform.require_output("ecr_repository_url")
global_db_secret_arn = data.require_output("global_db_secret_arn")

image_tag = config.get("image_tag") or "latest"
placeholder_image = pulumi.Output.concat(ecr_repository_url, f":{image_tag}")

identity_platform_realm = identity_stack.get_output("platform_realm").apply(
    lambda value: value or "soopa-platform"
)
identity_global_realm = identity_stack.get_output("global_realm").apply(
    lambda value: value or "soopa-global"
)
identity_admin_oauth_secret_arn = identity_stack.require_output("admin_oauth_secret_arn")

identity_jobs_queue_url = pubsub_env_vars["SQS_IDENTITY_JOBS_QUEUE_URL"]
notification_jobs_queue_url = pubsub_env_vars["SQS_NOTIFICATION_JOBS_QUEUE_URL"]
ucp_jobs_queue_url = pubsub_env_vars["SQS_UCP_JOBS_QUEUE_URL"]

_region = aws.get_region()
_identity = aws.get_caller_identity()

# ── IAM Execution Role (Platform Infrastructure Owned) ───────────────────────
execution_role_arn = platform.get_output("ecs_execution_role_arn").apply(
    lambda arn: arn or f"arn:aws:iam::{_identity.account_id}:role/{_prefix}ecs-execution-role"
)

# ── Task Definition ───────────────────────────────────────────────────────────
migrator_task = aws.ecs.TaskDefinition(
    f"{_prefix}db-migrator",
    family=f"{_prefix}db-migrator",
    cpu="512",
    memory="1024",
    network_mode="awsvpc",
    requires_compatibilities=["FARGATE"],
    execution_role_arn=execution_role_arn,
    task_role_arn=execution_role_arn,
    container_definitions=pulumi.Output.all(
        placeholder_image,
        global_db_secret_arn,
        identity_platform_realm,
        identity_global_realm,
        identity_admin_oauth_secret_arn,
        identity_jobs_queue_url,
        notification_jobs_queue_url,
        ucp_jobs_queue_url,
    ).apply(
        lambda args: json.dumps(
            [
                {
                    "name": "app",
                    "image": args[0],
                    "essential": True,
                    "command": [
                        "sh",
                        "-c",
                        "python -m platform_migrator migrate --domain platform && python infra/local/scripts/reconcile_schema_drift.py --domain platform --skip-dotenv && python -m platform_migrator seed --domain platform",
                    ],
                    "environment": [
                        {"name": "PUBSUB_TRANSPORT", "value": pubsub_env_vars["PUBSUB_TRANSPORT"]},
                        {"name": "IDENTITY_PROVIDER", "value": "casdoor"},
                        {"name": "IDENTITY_PLATFORM_REALM", "value": args[2]},
                        {"name": "IDENTITY_GLOBAL_REALM", "value": args[3]},
                        {"name": "IDENTITY_PLATFORM_ORG_ID", "value": args[2]},
                        {"name": "SQS_IDENTITY_JOBS_QUEUE_URL", "value": args[5]},
                        {"name": "SQS_NOTIFICATION_JOBS_QUEUE_URL", "value": args[6]},
                        {"name": "SQS_UCP_JOBS_QUEUE_URL", "value": args[7]},
                    ],
                    "secrets": [
                        {"name": "GLOBAL_DATABASE_URL", "valueFrom": f"{args[1]}:url::"},
                        {"name": "DATABASE_URL", "valueFrom": f"{args[1]}:url::"},
                        {
                            "name": "IDENTITY_PLATFORM_ADMIN_ID",
                            "valueFrom": f"{args[4]}:platform_admin_id::",
                        },
                    ],
                    "logConfiguration": {
                        "logDriver": "awslogs",
                        "options": {
                            "awslogs-group": f"/ecs/{_prefix}platform-migrator",
                            "awslogs-region": _region.name,
                            "awslogs-stream-prefix": "migrator",
                            "awslogs-create-group": "true",
                        },
                    },
                }
            ]
        )
    ),
    tags=_TAGS,
)

# ── Exports ───────────────────────────────────────────────────────────────────
pulumi.export("task_definition_family", migrator_task.family)
pulumi.export("task_definition_arn", migrator_task.arn)
pulumi.export("log_group", f"/ecs/{_prefix}platform-migrator")
pulumi.export("log_stream_prefix", "migrator")

pulumi.export(
    "cli_network_configuration",
    pulumi.Output.all(private_subnets, app_sg_id).apply(
        lambda args: json.dumps(
            {
                "awsvpcConfiguration": {
                    "subnets": args[0],
                    "securityGroups": [args[1]],
                    "assignPublicIp": "DISABLED",
                }
            }
        )
    ),
)
