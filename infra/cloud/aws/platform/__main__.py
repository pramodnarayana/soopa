"""
Platform Shared Services Layer (Layer 2)
========================================
Provisions core components used by all bounded contexts:
- ECS Fargate Cluster
- ECR Repository
- Global RDS PostgreSQL Database
- Self-Hosted Zitadel (Identity Provider)

Relies on Foundation layer for VPC and Networking.
"""

import json

import pulumi
import pulumi_aws as aws
import pulumi_random as random
from constants import (
    DatabaseConstants,
    EcsConstants,
    OpenObserveConstants,
    ZitadelConstants,
)

_env = pulumi.get_stack()
_prefix = f"{_env}-"
_TAGS = {"ManagedBy": "pulumi", "Component": "platform", "Environment": _env}

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "packages")))
from seedwork.ecs import provision_fargate_service
from seedwork.network import provision_alb, provision_target_group_and_rule

# ── Stack Reference to Foundation ─────────────────────────────────────────────
# We reference the foundation stack to retrieve VPC and Subnet IDs.
# Driven by config to allow cross-environment testing without hardcoded project names.
config = pulumi.Config()
enable_observability = config.get_bool("enable_observability") or False
foundation_stack_ref = config.get("foundation_stack") or f"foundation/{_env}"
foundation = pulumi.StackReference(foundation_stack_ref)

vpc_id = foundation.require_output("vpc_id")
public_subnets = [
    foundation.require_output("public_subnet_a_id"),
    foundation.require_output("public_subnet_b_id"),
]
private_subnets = [
    foundation.require_output("private_subnet_a_id"),
    foundation.require_output("private_subnet_b_id"),
]
app_sg_id = foundation.require_output("app_sg_id")
db_sg_id = foundation.require_output("db_sg_id")
main_alb_sg_id = foundation.require_output("main_alb_sg_id")

# ── Application Load Balancer ─────────────────────────────────────────────────
main_alb, main_listener, obs_listener = provision_alb(
    name=f"{_prefix}main",
    subnets=public_subnets,
    security_group_id=main_alb_sg_id,
    tags=_TAGS,
    certificate_arn=config.get("acm_certificate_arn"),
)

# ── ECR Repository ────────────────────────────────────────────────────────────
ecr_repo = aws.ecr.Repository(
    f"{_prefix}modular-monolith-repo",
    name=f"{_prefix}modular-monolith",
    image_scanning_configuration=aws.ecr.RepositoryImageScanningConfigurationArgs(
        scan_on_push=True,
    ),
    image_tag_mutability="MUTABLE",
    tags=_TAGS,
)

# Keep only the last 30 releases
aws.ecr.LifecyclePolicy(
    f"{_prefix}ecr-lifecycle",
    repository=ecr_repo.name,
    policy=json.dumps(
        {
            "rules": [
                {
                    "rulePriority": 1,
                    "description": "Keep last 30 images",
                    "selection": {
                        "tagStatus": "any",
                        "countType": "imageCountMoreThan",
                        "countNumber": 30,
                    },
                    "action": {"type": "expire"},
                }
            ]
        }
    ),
)

# ── ECS Cluster ───────────────────────────────────────────────────────────────
ecs_cluster = aws.ecs.Cluster(
    f"{_prefix}cluster",
    name=f"{_prefix}cluster",
    tags=_TAGS,
)

# Enable Container Insights
aws.ecs.ClusterCapacityProviders(
    f"{_prefix}cluster-cp",
    cluster_name=ecs_cluster.name,
    capacity_providers=[EcsConstants.CAPACITY_PROVIDER, "FARGATE_SPOT"],
    default_capacity_provider_strategies=[
        aws.ecs.ClusterCapacityProvidersDefaultCapacityProviderStrategyArgs(
            capacity_provider=EcsConstants.CAPACITY_PROVIDER,
            weight=1,
            base=1,
        )
    ],
)

# ── Global RDS PostgreSQL Database ────────────────────────────────────────────
db_subnet_group = aws.rds.SubnetGroup(
    f"{_prefix}db-subnet-group",
    subnet_ids=private_subnets,
    tags=_TAGS,
)

db_password = random.RandomPassword(
    "global-db-password",
    length=32,
)

config = pulumi.Config()
instance_class = config.get("db_instance_class") or DatabaseConstants.DEFAULT_INSTANCE_CLASS
allocated_storage = (
    config.get_int("db_allocated_storage") or DatabaseConstants.DEFAULT_ALLOCATED_STORAGE_GB
)

global_db = aws.rds.Instance(
    f"{_prefix}global-db",
    identifier=f"{_prefix}global-db",
    engine=DatabaseConstants.ENGINE,
    engine_version=DatabaseConstants.ENGINE_VERSION,
    instance_class=instance_class,
    allocated_storage=allocated_storage,
    db_name=DatabaseConstants.GLOBAL_DB_NAME,
    username=DatabaseConstants.MASTER_USERNAME,
    password=db_password.result,
    vpc_security_group_ids=[db_sg_id],
    db_subnet_group_name=db_subnet_group.name,
    skip_final_snapshot=False,
    final_snapshot_identifier=f"{_prefix}global-db-final-snapshot",
    publicly_accessible=False,
    tags=_TAGS,
)

db_secret = aws.secretsmanager.Secret(
    f"{_prefix}global-db-secret",
    name=f"edi/{_prefix}global-db-credentials",
    tags=_TAGS,
)

aws.secretsmanager.SecretVersion(
    f"{_prefix}global-db-secret-val",
    secret_id=db_secret.id,
    secret_string=pulumi.Output.all(global_db.address, global_db.port, db_password.result).apply(
        lambda args: json.dumps(
            {
                "host": args[0],
                "port": args[1],
                "username": DatabaseConstants.MASTER_USERNAME,
                "password": args[2],
                "dbname": DatabaseConstants.GLOBAL_DB_NAME,
            }
        )
    ),
)

# ── Zitadel Identity Provider (Self-Hosted) ───────────────────────────────────
# Zitadel requires a masterkey (32 bytes)
zitadel_masterkey = random.RandomPassword(
    "zitadel-masterkey",
    length=32,
)

zitadel_machinekey = random.RandomPassword(
    "zitadel-machinekey",
    length=32,
)

zitadel_masterkey_secret = aws.secretsmanager.Secret(
    f"{_prefix}zitadel-masterkey-secret",
    name=f"platform/{_prefix}zitadel-masterkey",
    tags=_TAGS,
)

aws.secretsmanager.SecretVersion(
    f"{_prefix}zitadel-masterkey-secret-val",
    secret_id=zitadel_masterkey_secret.id,
    secret_string=zitadel_masterkey.result,
)

zitadel_machinekey_secret = aws.secretsmanager.Secret(
    f"{_prefix}zitadel-machinekey-secret",
    name=f"platform/{_prefix}zitadel-machinekey",
    tags=_TAGS,
)

aws.secretsmanager.SecretVersion(
    f"{_prefix}zitadel-machinekey-secret-val",
    secret_id=zitadel_machinekey_secret.id,
    secret_string=zitadel_machinekey.result,
)

# ECS Execution Role (to pull image & read secrets)
ecs_execution_role = aws.iam.Role(
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
    role=ecs_execution_role.name,
    policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
)

aws.iam.RolePolicy(
    f"{_prefix}ecs-exec-role-secrets-policy",
    role=ecs_execution_role.id,
    policy=json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["secretsmanager:GetSecretValue"],
                    "Resource": [
                        db_secret.arn,
                        f"arn:aws:secretsmanager:{aws.get_region().name}:{aws.get_caller_identity().account_id}:secret:platform/{_prefix}*",
                    ],
                }
            ],
        }
    ),
)

_region = aws.get_region()
_identity = aws.get_caller_identity()

zitadel_listener = aws.lb.Listener(
    f"{_prefix}zitadel-listener",
    load_balancer_arn=main_alb.arn,
    port=443,
    protocol="HTTPS",
    ssl_policy="ELBSecurityPolicy-2016-08",
    certificate_arn=config.get("acm_certificate_arn"),
    default_actions=[
        aws.lb.ListenerDefaultActionArgs(
            type="fixed-response",
            fixed_response=aws.lb.ListenerDefaultActionFixedResponseArgs(
                content_type="text/plain",
                message_body="404: Not Found",
                status_code="404",
            ),
        )
    ],
    tags=_TAGS,
)

zitadel_tg = provision_target_group_and_rule(
    name=f"{_prefix}zitadel",
    vpc_id=vpc_id,
    listener_arn=zitadel_listener.arn,
    priority=100,
    path_pattern="/*",
    tags=_TAGS,
    port=ZitadelConstants.PORT,
)

# Zitadel Task Definition
zitadel_task = aws.ecs.TaskDefinition(
    f"{_prefix}zitadel-task",
    family=f"{_prefix}zitadel",
    cpu=ZitadelConstants.CPU,
    memory=ZitadelConstants.MEMORY,
    network_mode="awsvpc",
    requires_compatibilities=[EcsConstants.CAPACITY_PROVIDER],
    execution_role_arn=ecs_execution_role.arn,
    container_definitions=pulumi.Output.all(
        global_db.endpoint,
        db_password.result,
        zitadel_masterkey.result,
        zitadel_machinekey.result,
        db_secret.arn,
        zitadel_masterkey_secret.arn,
    ).apply(
        lambda args: json.dumps(
            [
                {
                    "name": ZitadelConstants.CONTAINER_NAME,
                    "image": ZitadelConstants.IMAGE,
                    "command": ["start-from-init", "--masterkey", args[2]],
                    "essential": True,
                    "portMappings": [
                        {"containerPort": ZitadelConstants.PORT, "hostPort": ZitadelConstants.PORT}
                    ],
                    "environment": [
                        {"name": "ZITADEL_DATABASE_POSTGRES_HOST", "value": args[0].split(":")[0]},
                        {"name": "ZITADEL_DATABASE_POSTGRES_PORT", "value": args[0].split(":")[1]},
                        {
                            "name": "ZITADEL_DATABASE_POSTGRES_USER",
                            "value": DatabaseConstants.MASTER_USERNAME,
                        },
                        {
                            "name": "ZITADEL_DATABASE_POSTGRES_DATABASE",
                            "value": DatabaseConstants.GLOBAL_DB_NAME,
                        },
                        {"name": "ZITADEL_EXTERNALSECURE", "value": "false"},
                        {"name": "ZITADEL_TLS_ENABLED", "value": "false"},
                    ],
                    "secrets": [
                        {
                            "name": "ZITADEL_DATABASE_POSTGRES_PASSWORD",
                            "valueFrom": f"{args[4]}:password::",
                        },
                        {
                            "name": "ZITADEL_MASTERKEY",
                            "valueFrom": args[5],
                        },
                    ],
                    "logConfiguration": {
                        "logDriver": EcsConstants.LOG_DRIVER,
                        "options": {
                            "awslogs-group": f"/ecs/{_prefix}zitadel",
                            "awslogs-region": _region.name,
                            "awslogs-stream-prefix": ZitadelConstants.CONTAINER_NAME,
                            "awslogs-create-group": "true",
                        },
                    },
                }
            ]
        )
    ),
    tags=_TAGS,
)

zitadel_svc = aws.ecs.Service(
    f"{_prefix}zitadel-svc",
    cluster=ecs_cluster.arn,
    task_definition=zitadel_task.arn,
    desired_count=1,
    launch_type=EcsConstants.CAPACITY_PROVIDER,
    network_configuration=aws.ecs.ServiceNetworkConfigurationArgs(
        subnets=private_subnets,
        security_groups=[app_sg_id],
        assign_public_ip=False,
    ),
    load_balancers=[
        aws.ecs.ServiceLoadBalancerArgs(
            target_group_arn=zitadel_tg.arn,
            container_name=ZitadelConstants.CONTAINER_NAME,
            container_port=ZitadelConstants.PORT,
        )
    ],
    tags=_TAGS,
)

pulumi.export("ecr_repository_url", ecr_repo.repository_url)
pulumi.export("ecs_cluster_arn", ecs_cluster.arn)
pulumi.export("ecs_cluster_name", ecs_cluster.name)
pulumi.export("global_db_endpoint", global_db.endpoint)
pulumi.export("global_db_secret_arn", db_secret.arn)
pulumi.export("zitadel_service_name", zitadel_svc.name)
pulumi.export("main_alb_listener_arn", main_listener.arn)
pulumi.export("main_alb_obs_listener_arn", obs_listener.arn)
pulumi.export("main_alb_dns_name", main_alb.dns_name)

# ── Observability ─────────────────────────────────────────────────────────────
enable_observability = config.get_bool("enable_observability")
if enable_observability:
    obs_bucket = aws.s3.Bucket(
        f"{_prefix}observability-data",
        bucket=f"{_prefix}observability-data",
        force_destroy=True,
        tags=_TAGS,
    )

    obs_tg = provision_target_group_and_rule(
        name=f"{_prefix}openobserve",
        vpc_id=vpc_id,
        listener_arn=obs_listener.arn,
        priority=100,
        path_pattern="/*",
        tags=_TAGS,
        port=5080,
    )

    obs_count = config.get_int("openobserve_desired_count")
    if obs_count is None:
        obs_count = 1

    obs_user_password = random.RandomPassword(
        "openobserve-password",
        length=32,
        special=True,
    )

    obs_user_secret = aws.secretsmanager.Secret(
        f"{_prefix}obs-user-secret",
        name=f"platform/{_prefix}openobserve-user",
        tags=_TAGS,
    )

    aws.secretsmanager.SecretVersion(
        f"{_prefix}obs-user-secret-val",
        secret_id=obs_user_secret.id,
        secret_string=OpenObserveConstants.DEFAULT_ADMIN_EMAIL,
    )

    obs_password_secret = aws.secretsmanager.Secret(
        f"{_prefix}obs-password-secret",
        name=f"platform/{_prefix}openobserve-password",
        tags=_TAGS,
    )

    aws.secretsmanager.SecretVersion(
        f"{_prefix}obs-password-secret-val",
        secret_id=obs_password_secret.id,
        secret_string=obs_user_password.result,
    )

    obs_svc = provision_fargate_service(
        name=f"{_prefix}openobserve",
        command=[],
        cluster_arn=ecs_cluster.arn,
        execution_role_arn=ecs_execution_role.arn,
        ecr_image_uri="public.ecr.aws/zinclabs/openobserve:v0.12.0",
        subnets=private_subnets,
        security_group_id=app_sg_id,
        tags=_TAGS,
        port=5080,
        target_group_arn=obs_tg.arn,
        desired_count=obs_count,
        obs_user_secret_arn=obs_user_secret.arn,
        obs_password_secret_arn=obs_password_secret.arn,
        environment_vars=[
            {"name": "ZO_DATA_DIR", "value": "/data"},
            {"name": "ZO_S3_BUCKET", "value": obs_bucket.bucket},
            {"name": "ZO_S3_REGION_NAME", "value": aws.get_region().name},
            {"name": "ZO_ROOT_USER_EMAIL", "value": "admin@example.com"},
            {"name": "ZO_ROOT_USER_PASSWORD", "value": obs_user_password.result},
        ],
    )

    pulumi.export("openobserve_endpoint", main_alb.dns_name.apply(lambda dns: f"{dns}:5080"))
