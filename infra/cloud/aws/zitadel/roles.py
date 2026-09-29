import json

import pulumi
import pulumi_aws as aws


def provision_roles(prefix: str, tags: dict, zitadel_machinekey_secret_arn, global_db_secret_arn):
    # Task Role (for containers to use at runtime)
    ecs_task_role = aws.iam.Role(
        f"{prefix}zitadel-task-role",
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

    aws.iam.RolePolicy(
        f"{prefix}zitadel-task-role-policy",
        role=ecs_task_role.id,
        policy=zitadel_machinekey_secret_arn.apply(
            lambda arn: json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": ["secretsmanager:PutSecretValue"],
                            "Resource": [arn],
                        },
                        {
                            "Effect": "Allow",
                            "Action": [
                                "ssmmessages:CreateControlChannel",
                                "ssmmessages:CreateDataChannel",
                                "ssmmessages:OpenControlChannel",
                                "ssmmessages:OpenDataChannel",
                            ],
                            "Resource": "*",
                        },
                    ],
                }
            )
        ),
    )

    # ECS Execution Role (to pull image & read secrets)
    ecs_execution_role = aws.iam.Role(
        f"{prefix}zitadel-execution-role",
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
        f"{prefix}zitadel-exec-role-attach",
        role=ecs_execution_role.name,
        policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
    )

    aws.iam.RolePolicy(
        f"{prefix}zitadel-exec-role-secrets-policy",
        role=ecs_execution_role.id,
        policy=pulumi.Output.all(
            global_db_secret_arn, aws.get_region().name, aws.get_caller_identity().account_id
        ).apply(
            lambda args: json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {"Effect": "Allow", "Action": ["logs:CreateLogGroup"], "Resource": "*"},
                        {
                            "Effect": "Allow",
                            "Action": ["secretsmanager:GetSecretValue"],
                            "Resource": [
                                args[0],
                                f"arn:aws:secretsmanager:{args[1]}:{args[2]}:secret:platform/{prefix}*",
                            ],
                        },
                    ],
                }
            )
        ),
    )

    return ecs_task_role, ecs_execution_role
