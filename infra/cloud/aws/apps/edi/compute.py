import json

import pulumi
import pulumi_aws as aws
from seedwork.ecs import provision_fargate_service


def provision_compute(
    prefix: str,
    tags: dict,
    vpc_id: str,
    private_subnets: list,
    public_subnets: list,
    app_sg_id: str,
    cluster_arn: str,
    ecr_image_uri: str,
    queues: dict,
    alb_listener_arn: str,
    topics: dict,
    edi_shard_db_endpoint: str,
    edi_shard_db_secret_arn: str,
    firelens_endpoint: str = None,
):
    _region = aws.get_region()
    _identity = aws.get_caller_identity()

    # Shared Execution Role
    execution_role = aws.iam.Role(
        f"{prefix}ecs-execution-role",
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
        f"{prefix}ecs-exec-role-attach",
        role=execution_role.name,
        policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
    )

    aws.iam.RolePolicy(
        f"{prefix}ecs-exec-role-secrets-policy",
        role=execution_role.id,
        policy=pulumi.Output.all(edi_shard_db_secret_arn).apply(
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

    def make_service(
        name: str,
        command: list,
        is_public: bool = False,
        port: int = None,
        target_group_arn: str = None,
        image_override: str = None,
        extra_env: list = None,
        secrets: list = None,
        enable_secrets_sidecar: bool = True,
    ):
        env_vars = []
        # Dynamically inject ALL queues into the environment
        for q_name, q_resource in queues.items():
            env_name = f"QUEUE_URL_{q_name.replace('-', '_').upper()}"
            env_vars.append({"name": env_name, "value": q_resource.url})

        # Dynamically inject ALL topics into the environment
        topic_arns = []
        for t_name, t_resource in topics.items():
            env_name = f"TOPIC_ARN_{t_name.replace('-', '_').upper()}"
            env_vars.append({"name": env_name, "value": t_resource.arn})
            topic_arns.append(t_resource.arn)

        if extra_env:
            env_vars.extend(extra_env)

        if enable_secrets_sidecar:
            # ── EDI Specific: Secrets Sidecar ──
            sidecar = {
                "name": "edi-secrets-sidecar",
                "command": ["python", "/app/apps/edi/apps/edi-secrets-sidecar/main.py"],
                "essential": True,
                "environment": [
                    {"name": "SECRETS_MOUNT_PATH", "value": "/mnt/secrets"},
                ],
                "mountPoints": [
                    {
                        "sourceVolume": "secrets",
                        "containerPath": "/mnt/secrets",
                        "readOnly": False,
                    }
                ],
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-group": f"/ecs/{prefix}{name}",
                        "awslogs-region": _region.name,
                        "awslogs-stream-prefix": "sidecar",
                        "awslogs-create-group": "true",
                    },
                },
            }

            extra_task_policy_statements = [
                {
                    "Sid": "SidecarGetSecretValue",
                    "Effect": "Allow",
                    "Action": ["secretsmanager:GetSecretValue"],
                    "Resource": f"arn:aws:secretsmanager:{_region.name}:{_identity.account_id}:secret:edi/*",
                },
            ]

            app_mount_points = [
                {
                    "sourceVolume": "secrets",
                    "containerPath": "/mnt/secrets",
                    "readOnly": True,
                }
            ]

            app_depends_on = [
                {
                    "containerName": "edi-secrets-sidecar",
                    "condition": "START",
                }
            ]

            volumes = [aws.ecs.TaskDefinitionVolumeArgs(name="secrets")]
        else:
            sidecar = None
            extra_task_policy_statements = []
            app_mount_points = []
            app_depends_on = []
            volumes = []

        return provision_fargate_service(
            name=f"{prefix}{name}",
            command=command,
            cluster_arn=cluster_arn,
            execution_role_arn=execution_role.arn,
            ecr_image_uri=image_override or ecr_image_uri,
            subnets=public_subnets if is_public else private_subnets,
            security_group_id=app_sg_id,
            tags=tags,
            environment_vars=env_vars,
            port=port,
            is_public=is_public,
            sidecar_container=sidecar,
            volumes=volumes,
            app_mount_points=app_mount_points,
            app_depends_on=app_depends_on,
            extra_task_policy_statements=extra_task_policy_statements,
            target_group_arn=target_group_arn,
            firelens_endpoint=firelens_endpoint,
            topic_arns=topic_arns if topic_arns else None,
            secrets=secrets,
        )

    # Extract the data plane topic for Debezium sink explicitly (it specifically requires it)
    data_plane_events_topic = topics.get("edi-data-plane-topic")
    if not data_plane_events_topic:
        raise ValueError("Missing required topic: 'edi-data-plane-topic' must be provisioned.")

    # 1. Debezium CDC Server
    debezium_server = make_service(
        "debezium-server",
        command=[],
        image_override="quay.io/debezium/server:3.6",
        enable_secrets_sidecar=False,
        extra_env=[
            {"name": "DEBEZIUM_SINK_TYPE", "value": "sns"},
            {
                "name": "DEBEZIUM_SINK_SNS_TOPIC_ARN",
                "value": data_plane_events_topic.arn,
            },
            {
                "name": "DEBEZIUM_SOURCE_DATABASE_HOSTNAME",
                "value": pulumi.Output.all(edi_shard_db_endpoint).apply(
                    lambda args: args[0].split(":")[0]
                ),
            },
            {
                "name": "DEBEZIUM_SOURCE_CONNECTOR_CLASS",
                "value": "io.debezium.connector.postgresql.PostgresConnector",
            },
            {
                "name": "DEBEZIUM_SOURCE_DATABASE_DBNAME",
                "value": "edi_shard",
            },
            {
                "name": "DEBEZIUM_SOURCE_TOPIC_PREFIX",
                "value": "edi_shard_events",
            },
            {
                "name": "DEBEZIUM_SOURCE_PLUGIN_NAME",
                "value": "pgoutput",
            },
            {
                "name": "DEBEZIUM_SOURCE_OFFSET_STORAGE",
                "value": "io.debezium.storage.jdbc.offset.JdbcOffsetBackingStore",
            },
            {
                "name": "DEBEZIUM_SOURCE_OFFSET_STORAGE_JDBC_URL",
                "value": pulumi.Output.all(edi_shard_db_endpoint).apply(
                    lambda args: f"jdbc:postgresql://{args[0]}/edi_shard"
                ),
            },
        ],
        secrets=[
            {
                "name": "DEBEZIUM_SOURCE_DATABASE_USER",
                "valueFrom": pulumi.Output.concat(edi_shard_db_secret_arn, ":username::"),
            },
            {
                "name": "DEBEZIUM_SOURCE_DATABASE_PASSWORD",
                "valueFrom": pulumi.Output.concat(edi_shard_db_secret_arn, ":password::"),
            },
            {
                "name": "DEBEZIUM_SOURCE_OFFSET_STORAGE_JDBC_USER",
                "valueFrom": pulumi.Output.concat(edi_shard_db_secret_arn, ":username::"),
            },
            {
                "name": "DEBEZIUM_SOURCE_OFFSET_STORAGE_JDBC_PASSWORD",
                "valueFrom": pulumi.Output.concat(edi_shard_db_secret_arn, ":password::"),
            },
        ],
    )

    return {
        "debezium_server": debezium_server,
    }
