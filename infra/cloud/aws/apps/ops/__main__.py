"""
Operations Bastion Layer
========================
Provisions a lightweight Fargate container with ECS Exec enabled
so developers can tunnel into the private RDS databases using SSM.
"""

import json

import pulumi
import pulumi_aws as aws
from infra_seedwork.ecs import provision_fargate_service

_env = pulumi.get_stack()
_prefix = f"{_env}-ops-"
_TAGS = {"ManagedBy": "pulumi", "Component": "ops", "Environment": _env}

config = pulumi.Config()
foundation_stack_ref = config.get("foundation_stack") or f"organization/foundation/{_env}"
platform_stack_ref = config.get("platform_stack") or f"organization/platform/{_env}"

foundation = pulumi.StackReference(foundation_stack_ref)
platform = pulumi.StackReference(platform_stack_ref)

vpc_id = foundation.require_output("vpc_id")
private_subnets = [
    foundation.require_output("private_subnet_a_id"),
    foundation.require_output("private_subnet_b_id"),
]
app_sg_id = foundation.require_output("app_sg_id")
ecs_cluster_arn = platform.require_output("ecs_cluster_arn")

data_stack_ref = config.get("data_stack") or f"organization/data/{_env}"
data = pulumi.StackReference(data_stack_ref)

global_db_endpoint = data.require_output("global_db_endpoint")
global_db_secret_arn = data.require_output("global_db_secret_arn")

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

aws.iam.RolePolicy(
    f"{_prefix}ecs-exec-secrets-policy",
    role=execution_role.id,
    policy=pulumi.Output.all(global_db_secret_arn).apply(
        lambda args: json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["secretsmanager:GetSecretValue"],
                        "Resource": [args[0]],
                    }
                ],
            }
        )
    ),
)

# Allow the task to read the DB secret
extra_policy = [
    {
        "Effect": "Allow",
        "Action": ["secretsmanager:GetSecretValue"],
        "Resource": [global_db_secret_arn],
    }
]

bastion_service = provision_fargate_service(
    name=f"{_prefix}bastion",
    command=["sh", "-c", "yum install -y postgresql15 && tail -f /dev/null"],
    cluster_arn=ecs_cluster_arn,
    execution_role_arn=execution_role.arn,
    ecr_image_uri="public.ecr.aws/amazonlinux/amazonlinux:2023",
    subnets=private_subnets,
    security_group_id=app_sg_id,
    tags=_TAGS,
    cpu="256",
    memory="512",
    enable_execute_command=True,
    desired_count=1,
    environment_vars=[
        {"name": "DB_ENDPOINT", "value": global_db_endpoint},
    ],
    secrets=[
        {
            "name": "DB_PASSWORD",
            "valueFrom": pulumi.Output.concat(global_db_secret_arn, ":password::"),
        },
    ],
    extra_task_policy_statements=extra_policy,
)
