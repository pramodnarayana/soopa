"""
Application Layer (Layer 3) - Unified API
"""

import ipaddress
import json
import os
import sys

sys.path.insert(0, os.path.abspath("../../packages"))

import pulumi
import pulumi_aws as aws
from seedwork.ecs import provision_fargate_service
from seedwork.network import provision_target_group_and_rule

_env = pulumi.get_stack()
_prefix = f"{_env}-api-"
_TAGS = {"ManagedBy": "pulumi", "Component": "api", "Environment": _env}

config = pulumi.Config()
foundation_stack_ref = config.get("foundation_stack") or f"foundation/{_env}"
platform_stack_ref = config.get("platform_stack") or f"platform/{_env}"

foundation = pulumi.StackReference(foundation_stack_ref)
platform = pulumi.StackReference(platform_stack_ref)

vpc_id = foundation.require_output("vpc_id")
private_subnets = [
    foundation.require_output("private_subnet_a_id"),
    foundation.require_output("private_subnet_b_id"),
]
app_sg_id = foundation.require_output("app_sg_id")

ecs_cluster_arn = platform.require_output("ecs_cluster_arn")
ecr_repository_url = platform.require_output("ecr_repository_url")
main_alb_listener_arn = platform.require_output("main_alb_listener_arn")

image_tag = config.get("image_tag") or "latest"
enable_observability = config.get_bool("enable_observability")
firelens_endpoint = (
    platform.require_output("openobserve_endpoint") if enable_observability else None
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
    command=[
        "uvicorn",
        "unified_api.main:app",
        "--host",
        str(ipaddress.IPv4Address(0)),
        "--port",
        "8000",
    ],
    cluster_arn=ecs_cluster_arn,
    execution_role_arn=execution_role.arn,
    ecr_image_uri=placeholder_image,
    subnets=private_subnets,
    security_group_id=app_sg_id,
    tags=_TAGS,
    firelens_endpoint=firelens_endpoint,
    port=8000,
    target_group_arn=api_tg.arn,
)
