"""
Application Layer (Layer 3) - Unified UCP Workers
==================================================
Provisions the consolidated UCP/Platform/Identity/Notification/EDI-CP worker
containers (all non-data-plane workers in the unified runner).

Environment variable injection is driven entirely by the ``queue_env_vars``
exports from each bounded-context messaging stack. No manual per-queue
env-var mapping exists here — adding a new queue to topology.json is
sufficient to make it available in every worker container.

Depends on: platform, foundation, data, edi/messaging, identity/messaging,
            notification/messaging, ucp/messaging.
"""

import json

import pulumi
import pulumi_aws as aws
from infra_seedwork.ecs import provision_fargate_service
from infra_seedwork.env import queue_env_vars_to_ecs_format

_env = pulumi.get_stack()
_prefix = f"{_env}-ucp-"
_TAGS = {"ManagedBy": "pulumi", "Component": "ucp-workers", "Environment": _env}

# ── Stack References ──────────────────────────────────────────────────────────
config = pulumi.Config()
foundation_stack_ref = config.get("foundation_stack") or f"organization/foundation/{_env}"
platform_stack_ref = config.get("platform_stack") or f"organization/platform/{_env}"
edi_messaging_stack_ref = config.get("edi_messaging_stack") or f"organization/edi-messaging/{_env}"
notification_stack_ref = config.get("notification_stack") or f"organization/notification/{_env}"
identity_stack_ref = config.get("identity_stack") or f"organization/identity/{_env}"
ucp_stack_ref = config.get("ucp_stack") or f"organization/ucp/{_env}"
data_stack_ref = config.get("data_stack") or f"organization/data/{_env}"

foundation = pulumi.StackReference(foundation_stack_ref)
platform = pulumi.StackReference(platform_stack_ref)
edi = pulumi.StackReference(edi_messaging_stack_ref)
notification = pulumi.StackReference(notification_stack_ref)
identity = pulumi.StackReference(identity_stack_ref)
ucp = pulumi.StackReference(ucp_stack_ref)
data = pulumi.StackReference(data_stack_ref)

# ── Infrastructure Inputs ─────────────────────────────────────────────────────
private_subnets = [
    foundation.require_output("private_subnet_a_id"),
    foundation.require_output("private_subnet_b_id"),
]
app_sg_id = foundation.require_output("app_sg_id")

ecs_cluster_arn = platform.require_output("ecs_cluster_arn")
ecr_repository_url = platform.require_output("ecr_repository_url")
staging_domain = platform.require_output("staging_domain")
app_defaults_secret_arn = platform.require_output("app_defaults_secret_arn")

edi_shard_db_endpoint = data.require_output("edi_shard_db_endpoint")
edi_shard_db_secret_arn = data.require_output("edi_shard_db_secret_arn")
global_db_endpoint = data.require_output("global_db_endpoint")
global_db_secret_arn = data.require_output("global_db_secret_arn")

image_tag = config.get("image_tag") or "latest"
enable_observability = config.get_bool("enable_observability")
firelens_endpoint = (
    platform.require_output("openobserve_endpoint") if enable_observability else None
)
placeholder_image = pulumi.Output.concat(ecr_repository_url, f":{image_tag}")

_region = aws.get_region()
_identity = aws.get_caller_identity()

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
    policy=pulumi.Output.all(
        edi_shard_db_secret_arn, global_db_secret_arn, app_defaults_secret_arn
    ).apply(
        lambda args: json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["secretsmanager:GetSecretValue"],
                        "Resource": [args[0], args[1], args[2]],
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

# ── EDI Secrets Sidecar ───────────────────────────────────────────────────────
sidecar = {
    "name": "edi-secrets-sidecar",
    "command": ["python", "/app/apps/edi/apps/edi-secrets-sidecar/main.py"],
    "essential": True,
    "environment": [
        {"name": "SECRETS_MOUNT_PATH", "value": "/mnt/secrets"},
    ],
    "mountPoints": [
        {
            "sourceVolume": "secrets",
            "containerPath": "/mnt/secrets",
            "readOnly": False,
        }
    ],
    "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
            "awslogs-group": f"/ecs/{_prefix}sidecar",
            "awslogs-region": _region.name,
            "awslogs-stream-prefix": "sidecar",
            "awslogs-create-group": "true",
        },
    },
}

extra_task_policy_statements = [
    {
        "Sid": "SidecarGetSecretValue",
        "Effect": "Allow",
        "Action": ["secretsmanager:GetSecretValue"],
        "Resource": f"arn:aws:secretsmanager:{_region.name}:{_identity.account_id}:secret:edi/*",
    },
    {
        "Sid": "SidecarListSecrets",
        "Effect": "Allow",
        "Action": ["secretsmanager:ListSecrets"],
        "Resource": "*",
    },
    {
        "Sid": "SqsPermissions",
        "Effect": "Allow",
        "Action": [
            "sqs:ReceiveMessage",
            "sqs:DeleteMessage",
            "sqs:GetQueueAttributes",
            "sqs:ChangeMessageVisibility",
            "sqs:SendMessage",
        ],
        "Resource": f"arn:aws:sqs:{_region.name}:{_identity.account_id}:*",
    },
    {
        "Sid": "SnsPermissions",
        "Effect": "Allow",
        "Action": ["sns:Publish"],
        "Resource": "*",
    },
]

app_mount_points = [
    {
        "sourceVolume": "secrets",
        "containerPath": "/mnt/secrets",
        "readOnly": True,
    }
]
app_depends_on = [{"containerName": "edi-secrets-sidecar", "condition": "START"}]
volumes = [aws.ecs.TaskDefinitionVolumeArgs(name="secrets")]

# ── Environment Variables — Topology-Driven ───────────────────────────────────
# Merge all ``queue_env_vars`` maps from every messaging stack into a single
# dict, then combine with static platform env vars. The result is the complete
# set of environment variables for every worker group.
#
# This is the enterprise SSOT pattern: adding a queue to topology.json and
# assigning it an env_var is sufficient — no changes to any compute stack.

all_queue_env_vars: pulumi.Output = pulumi.Output.all(
    edi=edi.require_output("queue_env_vars"),
    identity=identity.require_output("queue_env_vars"),
    notification=notification.require_output("queue_env_vars"),
    ucp=ucp.require_output("queue_env_vars"),
    platform_topic_arn=platform.require_output("sns_platform_events_topic_arn"),
).apply(
    lambda args: {
        **args["edi"],
        **args["identity"],
        **args["notification"],
        **args["ucp"],
        # SNS topic ARN — published by the platform stack, not a messaging stack.
        "SNS_PLATFORM_EVENTS_TOPIC_ARN": args["platform_topic_arn"],
    }
)

base_env_vars: pulumi.Output = pulumi.Output.all(
    queue_env_vars=all_queue_env_vars,
    global_db_host=global_db_endpoint,
    edi_db_host=edi_shard_db_endpoint,
    public_base_url=pulumi.Output.concat("https://api.", staging_domain),
    identity_issuer=pulumi.Output.concat("https://identity.", staging_domain),
).apply(
    lambda args: queue_env_vars_to_ecs_format(
        queue_env_vars=args["queue_env_vars"],
        static_vars={
            "ENVIRONMENT": _env,
            "GLOBAL_DB_HOST": args["global_db_host"],
            "EDI_DB_HOST": args["edi_db_host"],
            "PUBLIC_BASE_URL": args["public_base_url"],
            "IDENTITY_ISSUER": args["identity_issuer"],
        },
    )
)

# ── Worker Groups (from Pulumi config) ───────────────────────────────────────
worker_groups = config.require_object("worker_groups")

for group in worker_groups:
    group_env: pulumi.Output = base_env_vars.apply(
        lambda env, modules=group["modules"]: [
            *env,
            {"name": "WORKER_MODULES", "value": modules},
        ]
    )

    provision_fargate_service(
        name=f"{_prefix}{group['name']}",
        command=["python", "-m", "unified_worker.main"],
        cluster_arn=ecs_cluster_arn,
        execution_role_arn=execution_role.arn,
        ecr_image_uri=placeholder_image,
        subnets=private_subnets,
        security_group_id=app_sg_id,
        tags=_TAGS,
        environment_vars=group_env,
        sidecar_container=sidecar,
        volumes=volumes,
        app_mount_points=app_mount_points,
        app_depends_on=app_depends_on,
        extra_task_policy_statements=extra_task_policy_statements,
        firelens_endpoint=firelens_endpoint,
        secrets=[
            {
                "name": "GLOBAL_DATABASE_URL",
                "valueFrom": pulumi.Output.concat(global_db_secret_arn, ":url::"),
            },
            {
                "name": "DATABASE_URL",
                "valueFrom": pulumi.Output.concat(global_db_secret_arn, ":url::"),
            },
            {
                "name": "EDI_DATABASE_URL",
                "valueFrom": pulumi.Output.concat(edi_shard_db_secret_arn, ":url::"),
            },
            {
                "name": "SHARD_OVERRIDES__EDI_SHARD_1",
                "valueFrom": pulumi.Output.concat(edi_shard_db_secret_arn, ":async_url::"),
            },
            {
                "name": "IDENTITY_DEFAULT_USER_PASSWORD",
                "valueFrom": pulumi.Output.concat(
                    app_defaults_secret_arn, ":identity_default_user_password::"
                ),
            },
        ],
    )
