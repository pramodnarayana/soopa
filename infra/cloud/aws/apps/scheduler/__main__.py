"""
Application Layer (Layer 3) - Scheduler Bounded Context
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath("../../packages"))

import pulumi
import pulumi_aws as aws
from seedwork.ecs import provision_fargate_service

_env = pulumi.get_stack()
_prefix = f"{_env}-scheduler-"
_TAGS = {"ManagedBy": "pulumi", "Component": "scheduler", "Environment": _env}

config = pulumi.Config()
foundation_stack_ref = config.get("foundation_stack") or f"foundation/{_env}"
platform_stack_ref = config.get("platform_stack") or f"platform/{_env}"
edi_stack_ref = config.get("edi_stack") or f"edi/{_env}"
notification_stack_ref = config.get("notification_stack") or f"notification/{_env}"

foundation = pulumi.StackReference(foundation_stack_ref)
platform = pulumi.StackReference(platform_stack_ref)
edi = pulumi.StackReference(edi_stack_ref)
notification = pulumi.StackReference(notification_stack_ref)

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

edi_data_plane_jobs_q = edi.require_output("edi_data_plane_jobs_queue_url")
edi_control_plane_jobs_q = edi.require_output("edi_control_plane_jobs_queue_url")
notification_jobs_q = notification.require_output("notification_jobs_queue_url")

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

scheduler_worker = provision_fargate_service(
    name=f"{_prefix}worker",
    command=["python", "-m", "scheduler_worker.main"],
    cluster_arn=ecs_cluster_arn,
    execution_role_arn=execution_role.arn,
    ecr_image_uri=placeholder_image,
    subnets=private_subnets,
    security_group_id=app_sg_id,
    tags=_TAGS,
    firelens_endpoint=firelens_endpoint,
    environment_vars=[
        {"name": "SQS_DATA_PLANE_JOBS_QUEUE_URL", "value": edi_data_plane_jobs_q},
        {"name": "SQS_CONTROL_PLANE_JOBS_QUEUE_URL", "value": edi_control_plane_jobs_q},
        {"name": "SQS_NOTIFICATION_JOBS_QUEUE_URL", "value": notification_jobs_q},
    ],
)
