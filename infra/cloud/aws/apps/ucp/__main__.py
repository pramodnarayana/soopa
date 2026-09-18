"""
Application Layer (Layer 3) - UCP Bounded Context
===================================================
Provisions all UCP-specific infrastructure:
- UCP SQS Queues & SNS Topics (Messaging)
- UCP ECS Services (UCP Worker)

Relies on Foundation and Platform StackReferences.
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath("../../packages"))

import pulumi
import pulumi_aws as aws
from seedwork.ecs import provision_fargate_service
from seedwork.messaging import provision_fifo_queue_pair, subscribe_queue

_env = pulumi.get_stack()
_prefix = f"{_env}-ucp-"
_TAGS = {"ManagedBy": "pulumi", "Component": "ucp", "Environment": _env}

# ── Stack References ──────────────────────────────────────────────────────────
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

image_tag = config.get("image_tag") or "latest"
enable_observability = config.get_bool("enable_observability")
firelens_endpoint = (
    platform.require_output("openobserve_endpoint") if enable_observability else None
)
placeholder_image = pulumi.Output.concat(ecr_repository_url, f":{image_tag}")

# ── Messaging ─────────────────────────────────────────────────────────────────
events_topic = aws.sns.Topic(
    f"{_prefix}events",
    name=f"{_prefix}events.fifo",
    fifo_topic=True,
    content_based_deduplication=True,
    tags=_TAGS,
)

events_q, _ = provision_fifo_queue_pair(f"{_prefix}events", _TAGS)
jobs_q, _ = provision_fifo_queue_pair(f"{_prefix}jobs", _TAGS)

subscribe_queue(f"{_prefix}events-sub", events_topic, events_q)

# ── Compute ───────────────────────────────────────────────────────────────────
_region = aws.get_region()

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

ucp_worker = provision_fargate_service(
    name=f"{_prefix}worker",
    command=["python", "-m", "ucp_worker.main"],
    cluster_arn=ecs_cluster_arn,
    execution_role_arn=execution_role.arn,
    ecr_image_uri=placeholder_image,
    subnets=private_subnets,
    security_group_id=app_sg_id,
    tags=_TAGS,
    firelens_endpoint=firelens_endpoint,
    environment_vars=[
        {"name": "QUEUE_URL_UCP_EVENTS", "value": events_q.url},
        {"name": "QUEUE_URL_UCP_JOBS", "value": jobs_q.url},
    ],
)

# ── Exports ───────────────────────────────────────────────────────────────────
pulumi.export("ucp_events_topic_arn", events_topic.arn)
