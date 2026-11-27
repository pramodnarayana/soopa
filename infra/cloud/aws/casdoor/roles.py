"""Least-privilege ECS Task & Execution IAM roles for Casdoor."""

from __future__ import annotations

import json

import pulumi
import pulumi_aws as aws


def provision_roles(
    prefix: str,
    tags: dict[str, str],
    *,
    dsn_secret_arn: pulumi.Input[str],
    db_password_secret_arn: pulumi.Input[str],
    admin_password_secret_arn: pulumi.Input[str],
    global_db_secret_arn: pulumi.Input[str],
    region_name: str,
    account_id: str,
    enable_execute_command: bool = False,
    obs_user_secret_arn: pulumi.Input[str] | None = None,
    obs_password_secret_arn: pulumi.Input[str] | None = None,
) -> tuple[aws.iam.Role, aws.iam.Role]:
    assume_policy = json.dumps(
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
    )

    ecs_task_role = aws.iam.Role(
        f"{prefix}casdoor-task-role",
        assume_role_policy=assume_policy,
        tags=tags,
    )
    if enable_execute_command:
        aws.iam.RolePolicy(
            f"{prefix}casdoor-task-role-policy",
            role=ecs_task_role.id,
            policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": [
                                "ssmmessages:CreateControlChannel",
                                "ssmmessages:CreateDataChannel",
                                "ssmmessages:OpenControlChannel",
                                "ssmmessages:OpenDataChannel",
                            ],
                            "Resource": "*",
                        }
                    ],
                }
            ),
        )

    ecs_execution_role = aws.iam.Role(
        f"{prefix}casdoor-execution-role",
        assume_role_policy=assume_policy,
        tags=tags,
    )
    aws.iam.RolePolicyAttachment(
        f"{prefix}casdoor-exec-role-attach",
        role=ecs_execution_role.name,
        policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
    )

    scoped_log_group_arn = (
        f"arn:aws:logs:{region_name}:{account_id}:log-group:/ecs/{prefix}casdoor*"
    )
    aws.iam.RolePolicy(
        f"{prefix}casdoor-exec-role-secrets-policy",
        role=ecs_execution_role.id,
        policy=pulumi.Output.all(
            dsn_secret_arn,
            db_password_secret_arn,
            admin_password_secret_arn,
            global_db_secret_arn,
            obs_user_secret_arn,
            obs_password_secret_arn,
        ).apply(
            lambda args: json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": ["logs:CreateLogGroup"],
                            "Resource": scoped_log_group_arn,
                        },
                        {
                            "Effect": "Allow",
                            "Action": ["secretsmanager:GetSecretValue"],
                            "Resource": [arn for arn in args if arn],
                        },
                    ],
                }
            )
        ),
    )

    return ecs_task_role, ecs_execution_role
