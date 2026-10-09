"""
Application Layer (Layer 3) - EDI Bounded Context: AS2 Server
==============================================================
Provisions only the AS2 Server ECS Fargate service.

Tier 6: Deployed on every code push (image_tag change).
Depends on: edi/messaging (queue URLs), platform (cluster, ECR, ALB), data (DB).
"""

import json

import pulumi
import pulumi_aws as aws
from infra_seedwork.ecs import provision_fargate_service
from infra_seedwork.env import edi_environment_flag, queue_env_vars_to_ecs_format
from infra_seedwork.network import provision_target_group_and_rule

_env = pulumi.get_stack()
_prefix = f"{_env}-edi-"
_TAGS = {"ManagedBy": "pulumi", "Component": "edi-as2", "Environment": _env}

# ── Stack References ──────────────────────────────────────────────────────────
config = pulumi.Config()
foundation_stack_ref = config.get("foundation_stack") or f"organization/foundation/{_env}"
platform_stack_ref = config.get("platform_stack") or f"organization/platform/{_env}"
data_stack_ref = config.get("data_stack") or f"organization/data/{_env}"
messaging_stack_ref = config.get("messaging_stack") or f"organization/edi-messaging/{_env}"

foundation = pulumi.StackReference(foundation_stack_ref)
platform = pulumi.StackReference(platform_stack_ref)
data = pulumi.StackReference(data_stack_ref)
messaging = pulumi.StackReference(messaging_stack_ref)
# Storage stack is not used by AS2 server.
obs_stack_ref = config.get("openobserve_stack") or f"organization/organization-openobserve/{_env}"
obs = pulumi.StackReference(obs_stack_ref)

vpc_id = foundation.require_output("vpc_id")
private_subnets = [
    foundation.require_output("private_subnet_a_id"),
    foundation.require_output("private_subnet_b_id"),
]
app_sg_id = foundation.require_output("app_sg_id")

ecs_cluster_arn = platform.require_output("ecs_cluster_arn")
ecr_repository_url = platform.require_output("ecr_repository_url")
main_alb_listener_arn = platform.require_output("main_alb_listener_arn")
staging_domain = platform.require_output("staging_domain")
namespace_name = platform.require_output("cloud_map_namespace_name")

edi_shard_db_endpoint = data.require_output("edi_shard_db_endpoint")
edi_shard_db_secret_arn = data.require_output("edi_shard_db_secret_arn")
global_db_endpoint = data.require_output("global_db_endpoint")
global_db_secret_arn = data.require_output("global_db_secret_arn")

# S3 and SNS are not used by the AS2 server (payloads saved to DB).
queue_env_vars = messaging.require_output("queue_env_vars")
queue_arns = [
    messaging.require_output("sqs_edi_data_plane_jobs_arn"),
    messaging.require_output("sqs_edi_deliver_arn"),
    messaging.require_output("sqs_edi_orchestrator_arn"),
    messaging.require_output("sqs_edi_compute_arn"),
]

image_tag = config.get("image_tag") or "latest"
enable_observability = config.get_bool("enable_observability")
firelens_endpoint = (
    pulumi.Output.concat("openobserve.", namespace_name, ":5080") if enable_observability else None
)
obs_user_arn = obs.require_output("openobserve_user_secret_arn") if enable_observability else None
obs_pass_arn = (
    obs.require_output("openobserve_password_secret_arn") if enable_observability else None
)
ecr_image_uri = pulumi.Output.concat(ecr_repository_url, f":{image_tag}")

_region = aws.get_region()
_identity = aws.get_caller_identity()

# ── Execution Role ────────────────────────────────────────────────────────────
execution_role = aws.iam.Role(
    f"{_prefix}as2-ecs-execution-role",
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
    f"{_prefix}as2-ecs-exec-role-attach",
    role=execution_role.name,
    policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
)
aws.iam.RolePolicy(
    f"{_prefix}as2-ecs-exec-role-secrets-policy",
    role=execution_role.id,
    policy=pulumi.Output.all(
        edi_shard_db_secret_arn, global_db_secret_arn, obs_user_arn, obs_pass_arn
    ).apply(
        lambda args: json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["secretsmanager:GetSecretValue"],
                        "Resource": [arn for arn in [args[0], args[1], args[2], args[3]] if arn],
                    },
                    {"Effect": "Allow", "Action": ["logs:CreateLogGroup"], "Resource": "*"},
                ],
            }
        )
    ),
)

# ── EDI Secrets Sidecar ───────────────────────────────────────────────────────
sidecar = {
    "name": "edi-secrets-sidecar",
    "command": ["python", "/app/apps/edi/apps/edi-secrets-sidecar/main.py"],
    "essential": True,
    "user": "0",
    "environment": [{"name": "SECRETS_MOUNT_PATH", "value": "/mnt/secrets"}],
    "mountPoints": [
        {"sourceVolume": "secrets", "containerPath": "/mnt/secrets", "readOnly": False}
    ],
    "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
            "awslogs-group": f"/ecs/{_prefix}as2-sidecar",
            "awslogs-region": _region.name,
            "awslogs-stream-prefix": "sidecar",
            "awslogs-create-group": "true",
        },
    },
}
app_mount_points = [{"sourceVolume": "secrets", "containerPath": "/mnt/secrets", "readOnly": True}]
app_depends_on = [{"containerName": "edi-secrets-sidecar", "condition": "START"}]
volumes = [aws.ecs.TaskDefinitionVolumeArgs(name="secrets")]

# ── ALB Target Group ──────────────────────────────────────────────────────────
as2_tg = provision_target_group_and_rule(
    name=f"{_prefix}as2",
    vpc_id=vpc_id,
    listener_arn=main_alb_listener_arn,
    priority=405,
    path_pattern="/as2/*",
    host_header=pulumi.Output.concat("edi.", staging_domain),
    port=8001,
    tags=_TAGS,
)

# ── Environment Variables ─────────────────────────────────────────────────────
as2_env_vars: pulumi.Output = pulumi.Output.all(
    queue_env_vars=queue_env_vars,
    global_db_host=global_db_endpoint,
    edi_db_host=edi_shard_db_endpoint,
    public_base_url=pulumi.Output.concat("https://api.", staging_domain),
    as2_receive_url=pulumi.Output.concat("https://edi.", staging_domain, "/as2/inbox"),
    identity_issuer=pulumi.Output.concat("https://identity.", staging_domain),
).apply(
    lambda args: queue_env_vars_to_ecs_format(
        queue_env_vars=args["queue_env_vars"],
        static_vars={
            "AWS_REGION": _region.name,
            "ENVIRONMENT": _env,
            "EDI_ENVIRONMENT": edi_environment_flag(_env),
            "GLOBAL_DB_HOST": args["global_db_host"],
            "EDI_DB_HOST": args["edi_db_host"],
            "PUBLIC_BASE_URL": args["public_base_url"],
            "AS2_RECEIVE_URL": args["as2_receive_url"],
            "IDENTITY_ISSUER": args["identity_issuer"],
        },
    )
)

# ── AS2 Server ECS Service ────────────────────────────────────────────────────
as2_server = provision_fargate_service(
    name=f"{_prefix}as2-server",
    command=["uvicorn", "as2_server.main:app", "--host", "0.0.0.0", "--port", "8001"],  # noqa: S104 - Fargate container must bind to all interfaces to receive ALB traffic
    cluster_arn=ecs_cluster_arn,
    execution_role_arn=execution_role.arn,
    ecr_image_uri=ecr_image_uri,
    subnets=private_subnets,
    security_group_id=app_sg_id,
    tags=_TAGS,
    port=8001,
    target_group_arn=as2_tg.arn,
    sidecar_container=sidecar,
    volumes=volumes,
    app_mount_points=app_mount_points,
    app_depends_on=app_depends_on,
    firelens_endpoint=firelens_endpoint,
    obs_user_secret_arn=obs_user_arn,
    obs_password_secret_arn=obs_pass_arn,
    environment_vars=as2_env_vars,
    secrets=[
        {
            "name": "GLOBAL_DATABASE_URL",
            "valueFrom": pulumi.Output.concat(global_db_secret_arn, ":url::"),
        },
        {"name": "DATABASE_URL", "valueFrom": pulumi.Output.concat(global_db_secret_arn, ":url::")},
        {
            "name": "EDI_DATABASE_URL",
            "valueFrom": pulumi.Output.concat(edi_shard_db_secret_arn, ":url::"),
        },
        {
            "name": "DATABASE__SHARD_OVERRIDES__EDI_SHARD_1",
            "valueFrom": pulumi.Output.concat(edi_shard_db_secret_arn, ":async_url::"),
        },
    ],
    extra_task_policy_statements=[
        {
            "Effect": "Allow",
            "Action": ["secretsmanager:GetSecretValue"],
            "Resource": f"arn:aws:secretsmanager:{_region.name}:{_identity.account_id}:secret:edi/*",
        },
        {"Effect": "Allow", "Action": ["secretsmanager:ListSecrets"], "Resource": "*"},
        {
            "Effect": "Allow",
            "Action": [
                "sqs:SendMessage",
                "sqs:GetQueueAttributes",
            ],
            "Resource": queue_arns,
        },
    ],
)

# DNS Record moved to routing stack
pulumi.export("edi_domain", pulumi.Output.concat("edi.", staging_domain))
