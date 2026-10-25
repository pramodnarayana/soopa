"""
EDI Bounded Context - Database Migrator
======================================
Provisions the dedicated ECS Task Definition used by the CI/CD pipeline
(Release Phase) to run EDI migrations:
1. EDI Control Plane migrations on Global DB (edi.* schema).
2. Dynamic discovery of EDI tenant shards via ShardRegistry in Global DB.
3. EDI Data Plane migrations across all tenant shard databases.
"""

import json

import pulumi
import pulumi_aws as aws

_env = pulumi.get_stack()
_prefix = f"{_env}-edi-migrator-"
_TAGS = {"ManagedBy": "pulumi", "Component": "edi-migrator", "Environment": _env}

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
global_db_secret_arn = data.require_output("global_db_secret_arn")
edi_shard_db_secret_arn = data.require_output("edi_shard_db_secret_arn")

image_tag = config.get("image_tag") or "latest"
placeholder_image = pulumi.Output.concat(ecr_repository_url, f":{image_tag}")

_region = aws.get_region()

# ── IAM Execution Role (Platform Infrastructure Owned) ───────────────────────
# The ECS Task Execution Role is an infrastructure concern owned and pre-provisioned
# by the Platform stack (provision-infra.yml) to guarantee global IAM propagation
# before application rollout commences.
execution_role_arn = platform.require_output("ecs_execution_role_arn")

# ── Task Definition ───────────────────────────────────────────────────────────
edi_migrator_task = aws.ecs.TaskDefinition(
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
        edi_shard_db_secret_arn,
    ).apply(
        lambda args: json.dumps(
            [
                {
                    "name": "app",
                    "image": args[0],
                    "essential": True,
                    "command": [
                        "python",
                        "-m",
                        "edi.adapters.outbound.database.run_migrations",
                    ],
                    "secrets": [
                        {"name": "GLOBAL_DATABASE_URL", "valueFrom": f"{args[1]}:url::"},
                        {"name": "DATABASE_URL", "valueFrom": f"{args[1]}:url::"},
                        {"name": "EDI_DATABASE_URL", "valueFrom": f"{args[2]}:url::"},
                        {
                            "name": "DATABASE__SHARD_OVERRIDES__EDI_SHARD_1",
                            "valueFrom": f"{args[2]}:url::",
                        },
                    ],
                    "logConfiguration": {
                        "logDriver": "awslogs",
                        "options": {
                            "awslogs-group": f"/ecs/{_prefix}edi-migrator",
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
pulumi.export("task_definition_family", edi_migrator_task.family)
pulumi.export("task_definition_arn", edi_migrator_task.arn)
pulumi.export("log_group", f"/ecs/{_prefix}edi-migrator")
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
