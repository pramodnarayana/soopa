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

_env = pulumi.get_stack()
_prefix = f"{_env}-platform-migrator-"
_TAGS = {"ManagedBy": "pulumi", "Component": "platform-migrator", "Environment": _env}

# ── Stack References ──────────────────────────────────────────────────────────
config = pulumi.Config()
foundation_stack_ref = config.get("foundation_stack") or f"organization/foundation/{_env}"
platform_stack_ref = config.get("platform_stack") or f"organization/platform/{_env}"
data_stack_ref = config.get("data_stack") or f"organization/data/{_env}"

foundation = pulumi.StackReference(foundation_stack_ref)
platform = pulumi.StackReference(platform_stack_ref)
data = pulumi.StackReference(data_stack_ref)
zitadel_stack_ref = config.get("zitadel_stack") or f"organization/zitadel-infrastructure/{_env}"
zitadel = pulumi.StackReference(zitadel_stack_ref)
identity_stack_ref = config.get("identity_stack") or f"organization/identity/{_env}"
identity = pulumi.StackReference(identity_stack_ref)
notification_stack_ref = config.get("notification_stack") or f"organization/notification/{_env}"
notification = pulumi.StackReference(notification_stack_ref)
ucp_stack_ref = config.get("ucp_stack") or f"organization/ucp/{_env}"
ucp = pulumi.StackReference(ucp_stack_ref)

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

identity_platform_org_id = zitadel.require_output("platform_org_id")
identity_platform_admin_id = zitadel.require_output("platform_admin_id")
identity_edi_project_id = zitadel.require_output("edi_project_id")

identity_jobs_queue_url = identity.require_output("identity_jobs_queue_url")
notification_jobs_queue_url = notification.require_output("notification_jobs_queue_url")
ucp_jobs_queue_url = ucp.require_output("ucp_jobs_queue_url")

_region = aws.get_region()

# ── IAM Execution Role (Platform Infrastructure Owned) ───────────────────────
# The ECS Task Execution Role is an infrastructure concern owned and pre-provisioned
# by the Platform stack (provision-infra.yml) to guarantee global IAM propagation
# before application rollout commences.
execution_role_arn = platform.require_output("ecs_execution_role_arn")

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
        identity_platform_org_id,
        identity_platform_admin_id,
        identity_edi_project_id,
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
                        "python -m platform_migrator migrate --domain platform && python -m platform_migrator seed --domain all",
                    ],
                    "environment": [
                        {"name": "IDENTITY_PLATFORM_ORG_ID", "value": args[2]},
                        {"name": "IDENTITY_PLATFORM_ADMIN_ID", "value": args[3]},
                        {"name": "IDENTITY_EDI_PROJECT_ID", "value": args[4]},
                        {"name": "SQS_IDENTITY_JOBS_QUEUE_URL", "value": args[5]},
                        {"name": "SQS_NOTIFICATION_JOBS_QUEUE_URL", "value": args[6]},
                        {"name": "SQS_UCP_JOBS_QUEUE_URL", "value": args[7]},
                    ],
                    "secrets": [
                        {"name": "GLOBAL_DATABASE_URL", "valueFrom": f"{args[1]}:url::"},
                        {"name": "DATABASE_URL", "valueFrom": f"{args[1]}:url::"},
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
