"""
Application Layer (Layer 3) - EDI Bounded Context: DP Workers
==============================================================
Provisions the EDI Data Plane (DP) ECS Fargate workers:
  - edi-orchestrator-worker
  - edi-compute-worker
  - edi-delivery-worker
  - edi-dp-jobs-worker

Environment variable injection is driven entirely by the ``queue_env_vars``
export from the edi/messaging stack. No manual per-queue env-var mapping
exists here — adding a queue to topology.json is sufficient.

Tier 6: High-volume data plane processing. Deployed on code push.
Separate from CP workers to allow independent horizontal scaling.
Depends on: edi/messaging (queue_env_vars), platform (cluster, ECR), data (DB).
"""

import json

import pulumi
import pulumi_aws as aws
from infra_seedwork.ecs import provision_fargate_service
from infra_seedwork.env import edi_environment_flag, queue_env_vars_to_ecs_format

_env = pulumi.get_stack()
_prefix = f"{_env}-edi-"
_TAGS = {"ManagedBy": "pulumi", "Component": "edi-dp-workers", "Environment": _env}

# ── Stack References ──────────────────────────────────────────────────────────
config = pulumi.Config()
foundation_stack_ref = config.get("foundation_stack") or f"organization/foundation/{_env}"
platform_stack_ref = config.get("platform_stack") or f"organization/platform/{_env}"
data_stack_ref = config.get("data_stack") or f"organization/data/{_env}"
messaging_stack_ref = config.get("messaging_stack") or f"organization/edi-messaging/{_env}"
storage_stack_ref = config.get("storage_stack") or f"organization/edi-storage/{_env}"

foundation = pulumi.StackReference(foundation_stack_ref)
platform = pulumi.StackReference(platform_stack_ref)
data = pulumi.StackReference(data_stack_ref)
messaging = pulumi.StackReference(messaging_stack_ref)
storage = pulumi.StackReference(storage_stack_ref)
obs_stack_ref = config.get("openobserve_stack") or f"organization/organization-openobserve/{_env}"
obs = pulumi.StackReference(obs_stack_ref)

# ── Infrastructure Inputs ─────────────────────────────────────────────────────
private_subnets = [
    foundation.require_output("private_subnet_a_id"),
    foundation.require_output("private_subnet_b_id"),
]
app_sg_id = foundation.require_output("app_sg_id")

ecs_cluster_arn = platform.require_output("ecs_cluster_arn")
ecr_repository_url = platform.require_output("ecr_repository_url")
staging_domain = platform.require_output("staging_domain")
namespace_name = platform.require_output("cloud_map_namespace_name")

edi_shard_db_endpoint = data.require_output("edi_shard_db_endpoint")
edi_shard_db_secret_arn = data.require_output("edi_shard_db_secret_arn")
global_db_endpoint = data.require_output("global_db_endpoint")
global_db_secret_arn = data.require_output("global_db_secret_arn")

as2_payloads_bucket_name = storage.require_output("as2_payloads_bucket_name")
as2_payloads_bucket_arn = storage.require_output("as2_payloads_bucket_arn")
sns_platform_events_topic_arn = platform.require_output("sns_platform_events_topic_arn")
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

# ── IAM Execution Role ────────────────────────────────────────────────────────
execution_role = aws.iam.Role(
    f"{_prefix}dp-workers-ecs-execution-role",
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
    f"{_prefix}dp-workers-ecs-exec-role-attach",
    role=execution_role.name,
    policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
)
aws.iam.RolePolicy(
    f"{_prefix}dp-workers-ecs-exec-role-policy",
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
            "awslogs-group": f"/ecs/{_prefix}dp-workers-sidecar",
            "awslogs-region": _region.name,
            "awslogs-stream-prefix": "sidecar",
            "awslogs-create-group": "true",
        },
    },
}
app_mount_points = [{"sourceVolume": "secrets", "containerPath": "/mnt/secrets", "readOnly": True}]
app_depends_on = [{"containerName": "edi-secrets-sidecar", "condition": "START"}]
volumes = [aws.ecs.TaskDefinitionVolumeArgs(name="secrets")]

# ── Environment Variables — Topology-Driven ───────────────────────────────────
# The edi/messaging stack exports ``queue_env_vars``: a structured map of
# { "SQS_ORCHESTRATOR_QUEUE_URL": "https://...", ... } for every EDI queue
# and topic that declares an env_var in topology.json.
#
# We merge this with static platform env vars and convert to ECS format.
# No per-queue manual mapping ever needed here.

dp_worker_env_vars: pulumi.Output = pulumi.Output.all(
    queue_env_vars=messaging.require_output("queue_env_vars"),
    global_db_host=global_db_endpoint,
    edi_db_host=edi_shard_db_endpoint,
    public_base_url=pulumi.Output.concat("https://api.", staging_domain),
    identity_issuer=pulumi.Output.concat("https://identity.", staging_domain),
    identity_api_url=pulumi.Output.concat(
        "https://identity.", platform.require_output("staging_domain")
    ),
    s3_bucket=as2_payloads_bucket_name,
).apply(
    lambda args: queue_env_vars_to_ecs_format(
        queue_env_vars=args["queue_env_vars"],
        static_vars={
            "ENVIRONMENT": _env,
            "EDI_ENVIRONMENT": edi_environment_flag(_env),
            "GLOBAL_DB_HOST": args["global_db_host"],
            "EDI_DB_HOST": args["edi_db_host"],
            "PUBLIC_BASE_URL": args["public_base_url"],
            "IDENTITY_ISSUER": args["identity_issuer"],
            "IDENTITY_API_URL": args["identity_api_url"],
            "S3_BUCKET": args["s3_bucket"],
            "WORKER_MODULES": "edi-orchestrator-worker,edi-compute-worker,edi-delivery-worker,edi-dp-jobs-worker",
        },
    )
)

# ── DP Workers ECS Service ────────────────────────────────────────────────────
provision_fargate_service(
    name=f"{_prefix}dp-workers",
    command=["python", "-m", "unified_worker.main"],
    cluster_arn=ecs_cluster_arn,
    execution_role_arn=execution_role.arn,
    ecr_image_uri=ecr_image_uri,
    subnets=private_subnets,
    security_group_id=app_sg_id,
    tags=_TAGS,
    environment_vars=dp_worker_env_vars,
    sidecar_container=sidecar,
    volumes=volumes,
    app_mount_points=app_mount_points,
    app_depends_on=app_depends_on,
    firelens_endpoint=firelens_endpoint,
    obs_user_secret_arn=obs_user_arn,
    obs_password_secret_arn=obs_pass_arn,
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
            "Action": ["sns:Publish"],
            "Resource": [sns_platform_events_topic_arn],
        },
        {
            "Effect": "Allow",
            "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
            "Resource": pulumi.Output.concat(as2_payloads_bucket_arn, "/*"),
        },
        {
            "Effect": "Allow",
            "Action": ["s3:ListBucket"],
            "Resource": as2_payloads_bucket_arn,
        },
        {
            "Effect": "Allow",
            "Action": [
                "sqs:SendMessage",
                "sqs:ReceiveMessage",
                "sqs:DeleteMessage",
                "sqs:GetQueueAttributes",
                "sqs:ChangeMessageVisibility",
            ],
            "Resource": queue_arns,
        },
    ],
)
