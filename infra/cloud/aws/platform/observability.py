import json
import os

import pulumi
import pulumi_aws as aws
import pulumi_random as random
from constants import OpenObserveConstants
from dotenv import load_dotenv

_WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
load_dotenv(os.path.join(_WORKSPACE_ROOT, "versions.env"))

from infra_seedwork.ecs import provision_fargate_service
from infra_seedwork.network import provision_target_group_and_rule


def provision_openobserve(
    prefix: str,
    tags: dict,
    vpc_id: str,
    private_subnets: list,
    app_sg_id: str,
    ecs_cluster_arn: str,
    obs_listener_arn: str,
    obs_count: int,
):
    obs_bucket = aws.s3.Bucket(
        f"{prefix}observability-data",
        bucket=f"{prefix}observability-data",
        force_destroy=True,
        tags=tags,
    )

    obs_tg = provision_target_group_and_rule(
        name=f"{prefix}openobserve",
        vpc_id=vpc_id,
        listener_arn=obs_listener_arn,
        priority=100,
        path_pattern="/*",
        tags=tags,
        port=5080,
    )

    obs_user_password = random.RandomPassword(
        "openobserve-password",
        length=32,
        special=True,
    )

    is_prod = pulumi.get_stack() == "production"

    obs_user_secret = aws.secretsmanager.Secret(
        f"{prefix}obs-user-secret",
        name_prefix=f"platform/{prefix}openobserve-user-",
        recovery_window_in_days=30 if is_prod else 0,
        tags=tags,
    )

    aws.secretsmanager.SecretVersion(
        f"{prefix}obs-user-secret-val",
        secret_id=obs_user_secret.id,
        secret_string=OpenObserveConstants.DEFAULT_ADMIN_EMAIL,
    )

    obs_password_secret = aws.secretsmanager.Secret(
        f"{prefix}obs-password-secret",
        name_prefix=f"platform/{prefix}openobserve-password-",
        recovery_window_in_days=30 if is_prod else 0,
        tags=tags,
    )

    aws.secretsmanager.SecretVersion(
        f"{prefix}obs-password-secret-val",
        secret_id=obs_password_secret.id,
        secret_string=obs_user_password.result,
    )

    obs_exec_role = aws.iam.Role(
        f"{prefix}obs-exec-role",
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
        tags=tags,
    )
    aws.iam.RolePolicyAttachment(
        f"{prefix}obs-exec-role-attach",
        role=obs_exec_role.name,
        policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
    )
    aws.iam.RolePolicy(
        f"{prefix}obs-exec-role-secrets-policy",
        role=obs_exec_role.id,
        policy=pulumi.Output.all(aws.get_region().name, aws.get_caller_identity().account_id).apply(
            lambda args: json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": ["secretsmanager:GetSecretValue"],
                            "Resource": [
                                f"arn:aws:secretsmanager:{args[0]}:{args[1]}:secret:platform/{prefix}openobserve*",
                            ],
                        }
                    ],
                }
            )
        ),
    )

    aws.cloudwatch.LogGroup(
        f"{prefix}openobserve-log-group",
        name=f"/ecs/{prefix}openobserve",
        retention_in_days=3,
        tags=tags,
    )

    obs_svc = provision_fargate_service(
        name=f"{prefix}openobserve",
        command=[],
        cluster_arn=ecs_cluster_arn,
        execution_role_arn=obs_exec_role.arn,
        ecr_image_uri=f"public.ecr.aws/zinclabs/openobserve:{os.environ['OPENOBSERVE_VERSION']}",
        subnets=private_subnets,
        security_group_id=app_sg_id,
        tags=tags,
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
        ],
        secrets=[
            {"name": "ZO_ROOT_USER_PASSWORD", "valueFrom": obs_password_secret.arn},
        ],
    )

    return obs_svc
