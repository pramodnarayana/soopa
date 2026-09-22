"""
Application Layer (Layer 3) - Unified Workers
=============================================
Provisions the consolidated CP and DP worker containers based on configuration.
Relies on all other bounded contexts to get their respective Queue URLs.
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath("../../packages"))

import pulumi
import pulumi_aws as aws
from seedwork.ecs import provision_fargate_service

_env = pulumi.get_stack()
_prefix = f"{_env}-workers-"
_TAGS = {"ManagedBy": "pulumi", "Component": "workers", "Environment": _env}

config = pulumi.Config()
foundation_stack_ref = config.get("foundation_stack") or f"foundation/{_env}"
platform_stack_ref = config.get("platform_stack") or f"platform/{_env}"
edi_stack_ref = config.get("edi_stack") or f"edi/{_env}"
notification_stack_ref = config.get("notification_stack") or f"notification/{_env}"
identity_stack_ref = config.get("identity_stack") or f"identity/{_env}"
ucp_stack_ref = config.get("ucp_stack") or f"ucp/{_env}"

foundation = pulumi.StackReference(foundation_stack_ref)
platform = pulumi.StackReference(platform_stack_ref)
edi = pulumi.StackReference(edi_stack_ref)
notification = pulumi.StackReference(notification_stack_ref)
identity = pulumi.StackReference(identity_stack_ref)
ucp = pulumi.StackReference(ucp_stack_ref)

vpc_id = foundation.require_output("vpc_id")
private_subnets = [
    foundation.require_output("private_subnet_a_id"),
    foundation.require_output("private_subnet_b_id"),
]
app_sg_id = foundation.require_output("app_sg_id")

ecs_cluster_arn = platform.require_output("ecs_cluster_arn")
ecr_repository_url = platform.require_output("ecr_repository_url")

image_tag = config.get("image_tag") or "latest"
enable_observability = config.get_bool("enable_observability")
firelens_endpoint = (
    platform.require_output("openobserve_endpoint") if enable_observability else None
)
placeholder_image = pulumi.Output.concat(ecr_repository_url, f":{image_tag}")

_region = aws.get_region()
_identity = aws.get_caller_identity()

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
aws.iam.RolePolicyAttachment(
    f"{_prefix}ecs-exec-role-attach",
    role=execution_role.name,
    policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
)

# ── EDI Specific: Secrets Sidecar ──
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
]

app_mount_points = [
    {
        "sourceVolume": "secrets",
        "containerPath": "/mnt/secrets",
        "readOnly": True,
    }
]

app_depends_on = [
    {
        "containerName": "edi-secrets-sidecar",
        "condition": "START",
    }
]

volumes = [aws.ecs.TaskDefinitionVolumeArgs(name="secrets")]

# Gather all queue URLs from other stacks
env_vars = [
    {"name": "QUEUE_URL_EDI_TRANSFORM", "value": edi.require_output("sqs_transform_queue_url")},
    {"name": "QUEUE_URL_EDI_LIFECYCLE", "value": edi.require_output("sqs_lifecycle_queue_url")},
    {"name": "QUEUE_URL_EDI_DELIVER", "value": edi.require_output("sqs_deliver_queue_url")},
    {"name": "QUEUE_URL_EDI_CONFIG_SYNC", "value": edi.require_output("sqs_config_sync_queue_url")},
    {
        "name": "QUEUE_URL_EDI_DATA_PLANE_JOBS",
        "value": edi.require_output("sqs_data_plane_jobs_queue_url"),
    },
    {
        "name": "QUEUE_URL_EDI_CONTROL_PLANE_JOBS",
        "value": edi.require_output("sqs_control_plane_jobs_queue_url"),
    },
    {
        "name": "SQS_DATA_PLANE_JOBS_QUEUE_URL",
        "value": edi.require_output("sqs_data_plane_jobs_queue_url"),
    },
    {
        "name": "SQS_CONTROL_PLANE_JOBS_QUEUE_URL",
        "value": edi.require_output("sqs_control_plane_jobs_queue_url"),
    },
    {
        "name": "SQS_PRIORITY_NOTIFICATIONS_QUEUE_URL",
        "value": edi.require_output("sqs_priority_notifications_queue_url"),
    },
    {
        "name": "QUEUE_URL_IDENTITY_EVENTS",
        "value": identity.require_output("identity_jobs_queue_url"),
    },
    {
        "name": "SQS_IDENTITY_JOBS_QUEUE_URL",
        "value": identity.require_output("identity_jobs_queue_url"),
    },
    {"name": "QUEUE_URL_UCP_EVENTS", "value": ucp.require_output("ucp_jobs_queue_url")},
    {"name": "QUEUE_URL_UCP_JOBS", "value": ucp.require_output("ucp_jobs_queue_url")},
    {"name": "SQS_UCP_JOBS_QUEUE_URL", "value": ucp.require_output("ucp_jobs_queue_url")},
    {
        "name": "QUEUE_URL_NOTIFICATION_EMAIL",
        "value": notification.require_output("email_channel_queue_url"),
    },
    {
        "name": "SQS_NOTIFICATION_JOBS_QUEUE_URL",
        "value": notification.require_output("notification_jobs_queue_url"),
    },
]

worker_groups = config.require_object("worker_groups")

for group in worker_groups:
    group_env = env_vars.copy()
    group_env.append({"name": "WORKER_MODULES", "value": group["modules"]})

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
    )
