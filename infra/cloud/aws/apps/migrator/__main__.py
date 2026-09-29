"""
Application Layer (Layer 3) - Database Migrator
===============================================
Provisions the dedicated ECS Task Definition used by the CI/CD pipeline
(Release Phase) to run Alembic database migrations.

This stack ONLY provisions the template. The actual execution is triggered
via `aws ecs run-task` by the CI/CD workflow.
"""

import json

import pulumi
import pulumi_aws as aws

_env = pulumi.get_stack()
_prefix = f"{_env}-migrator-"
_TAGS = {"ManagedBy": "pulumi", "Component": "migrator", "Environment": _env}

# ── Stack References ──────────────────────────────────────────────────────────
config = pulumi.Config()
foundation_stack_ref = config.get("foundation_stack") or f"organization/foundation/{_env}"
platform_stack_ref = config.get("platform_stack") or f"organization/platform/{_env}"
data_stack_ref = config.get("data_stack") or f"organization/data/{_env}"

foundation = pulumi.StackReference(foundation_stack_ref)
platform = pulumi.StackReference(platform_stack_ref)
data = pulumi.StackReference(data_stack_ref)

# ── Infrastructure Inputs ─────────────────────────────────────────────────────
private_subnets = [
    foundation.require_output("private_subnet_a_id"),
    foundation.require_output("private_subnet_b_id"),
]
app_sg_id = foundation.require_output("app_sg_id")

ecr_repository_url = platform.require_output("ecr_repository_url")
edi_shard_db_secret_arn = data.require_output("edi_shard_db_secret_arn")
global_db_secret_arn = data.require_output("global_db_secret_arn")

image_tag = config.get("image_tag") or "latest"
placeholder_image = pulumi.Output.concat(ecr_repository_url, f":{image_tag}")

_region = aws.get_region()

# ── IAM Execution Role ────────────────────────────────────────────────────────
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
    policy=pulumi.Output.all(edi_shard_db_secret_arn, global_db_secret_arn).apply(
        lambda args: json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["secretsmanager:GetSecretValue"],
                        "Resource": [args[0], args[1]],
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

# ── Task Definition ───────────────────────────────────────────────────────────
migrator_task = aws.ecs.TaskDefinition(
    f"{_prefix}db-migrator",
    family=f"{_prefix}db-migrator",
    cpu="512",
    memory="1024",
    network_mode="awsvpc",
    requires_compatibilities=["FARGATE"],
    execution_role_arn=execution_role.arn,
    task_role_arn=execution_role.arn,
    container_definitions=pulumi.Output.all(
        placeholder_image, global_db_secret_arn, edi_shard_db_secret_arn
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
                        "cd /app/core/platform/packages/database && alembic upgrade head && cd /app/apps/edi/packages/edi && python src/edi/adapters/outbound/database/run_migrations.py",
                    ],
                    "secrets": [
                        {"name": "GLOBAL_DATABASE_URL", "valueFrom": f"{args[1]}:url::"},
                        {"name": "DATABASE_URL", "valueFrom": f"{args[1]}:url::"},
                        {"name": "EDI_DATABASE_URL", "valueFrom": f"{args[2]}:url::"},
                    ],
                    "logConfiguration": {
                        "logDriver": "awslogs",
                        "options": {
                            "awslogs-group": f"/ecs/{_prefix}migrator",
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
