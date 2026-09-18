import ipaddress
import json

import pulumi_aws as aws
from seedwork.ecs import provision_fargate_service
from seedwork.network import provision_target_group_and_rule


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

    def make_service(
        name: str,
        command: list,
        is_public: bool = False,
        port: int = None,
        target_group_arn: str = None,
    ):
        env_vars = [
            {"name": "QUEUE_URL_EDI_TRANSFORM", "value": queues["transform"].url},
            {"name": "QUEUE_URL_EDI_COMPUTE", "value": queues["compute"].url},
            {"name": "QUEUE_URL_EDI_LIFECYCLE", "value": queues["lifecycle"].url},
            {"name": "QUEUE_URL_EDI_DELIVER", "value": queues["deliver"].url},
            {"name": "QUEUE_URL_EDI_CONFIG_SYNC", "value": queues["config_sync"].url},
            {"name": "QUEUE_URL_EDI_DATA_PLANE_JOBS", "value": queues["data_plane_jobs"].url},
            {"name": "QUEUE_URL_EDI_CONTROL_PLANE_JOBS", "value": queues["control_plane_jobs"].url},
        ]

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

        return provision_fargate_service(
            name=f"{prefix}{name}",
            command=command,
            cluster_arn=cluster_arn,
            execution_role_arn=execution_role.arn,
            ecr_image_uri=ecr_image_uri,
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
        )

    # Define the 5 Shopify-style workers (same image, different entrypoints)
    # 1. AS2 Server (HTTP)
    as2_tg = provision_target_group_and_rule(
        name=f"{prefix}as2",
        vpc_id=vpc_id,
        listener_arn=alb_listener_arn,
        priority=100,  # EDI AS2 gets priority 100
        path_pattern="/as2/*",
        tags=tags,
    )

    as2_server = make_service(
        "as2-server",
        [
            "uvicorn",
            "as2_server.main:app",
            "--host",
            str(ipaddress.IPv4Address(0)),
            "--port",
            "8000",
        ],
        port=8000,
        target_group_arn=as2_tg.arn,
    )

    # 2. Background Worker
    background_worker = make_service(
        "background-worker", ["python", "-m", "edi_background_worker.main"]
    )

    # 3. Compute Worker
    compute_worker = make_service("compute-worker", ["python", "-m", "compute_worker.main"])

    # 4. Orchestrator Worker
    orchestrator_worker = make_service("orchestrator-worker", ["python", "-m", "worker.main"])

    # 5. Config Sync Worker
    config_sync_worker = make_service(
        "config-sync-worker", ["python", "-m", "config_sync_worker.provision.main"]
    )

    return {
        "as2_server": as2_server,
        "background_worker": background_worker,
        "compute_worker": compute_worker,
        "orchestrator_worker": orchestrator_worker,
        "config_sync_worker": config_sync_worker,
    }
