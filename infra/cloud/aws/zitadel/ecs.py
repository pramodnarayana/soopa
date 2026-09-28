import json

import pulumi
import pulumi_aws as aws
from constants import DatabaseConstants, EcsConstants, ZitadelConstants
from infra_seedwork.network import provision_target_group_and_rule


def provision_ecs(
    prefix,
    tags,
    vpc_id,
    private_subnets,
    app_sg_id,
    ecs_cluster_arn,
    main_listener_arn,
    main_alb_dns_name,
    global_db_endpoint,
    global_db_password,
    global_db_secret_arn,
    zitadel_ecr_repo_url,
    zitadel_masterkey,
    zitadel_admin_password,
    zitadel_masterkey_secret_arn,
    zitadel_machinekey_secret_arn,
    zitadel_admin_password_secret_arn,
    ecs_task_role_arn,
    ecs_execution_role_arn,
):

    zitadel_tg = provision_target_group_and_rule(
        name=f"{prefix}zitadel",
        vpc_id=vpc_id,
        listener_arn=main_listener_arn,
        priority=95,
        path_pattern="/*",
        host_header=pulumi.Output.concat(
            "identity.", main_alb_dns_name
        ),  # In __main__.py, we will pass 'identity.staging.flowwolf.io' to this parameter
        tags=tags,
        port=ZitadelConstants.PORT,
        health_check_path="/debug/healthz",
        protocol_version="HTTP2",
    )

    aws.cloudwatch.LogGroup(
        f"{prefix}zitadel-log-group",
        name=f"/ecs/{prefix}zitadel",
        retention_in_days=3,
        tags=tags,
    )

    zitadel_task = aws.ecs.TaskDefinition(
        f"{prefix}zitadel-task",
        family=f"{prefix}zitadel",
        cpu=ZitadelConstants.CPU,
        memory=ZitadelConstants.MEMORY,
        network_mode="awsvpc",
        requires_compatibilities=[EcsConstants.CAPACITY_PROVIDER],
        execution_role_arn=ecs_execution_role_arn,
        task_role_arn=ecs_task_role_arn,
        volumes=[aws.ecs.TaskDefinitionVolumeArgs(name="machinekey-vol")],
        container_definitions=pulumi.Output.all(
            global_db_endpoint,
            global_db_password,
            zitadel_masterkey,
            zitadel_admin_password,
            global_db_secret_arn,
            zitadel_masterkey_secret_arn,
            zitadel_machinekey_secret_arn,
            aws.get_region().name,
            zitadel_ecr_repo_url,
            zitadel_admin_password_secret_arn,
            main_alb_dns_name,
        ).apply(
            lambda args: json.dumps(
                [
                    {
                        "name": ZitadelConstants.CONTAINER_NAME,
                        "image": f"{args[8]}:{ZitadelConstants.IMAGE.split(':')[-1]}",
                        "command": ["start-from-init", "--masterkeyFromEnv"],
                        "essential": True,
                        "dependsOn": [{"containerName": "init-volume", "condition": "SUCCESS"}],
                        "mountPoints": [
                            {"sourceVolume": "machinekey-vol", "containerPath": "/machinekey"}
                        ],
                        "portMappings": [
                            {
                                "containerPort": ZitadelConstants.PORT,
                                "hostPort": ZitadelConstants.PORT,
                            }
                        ],
                        "environment": [
                            {
                                "name": "ZITADEL_DATABASE_POSTGRES_HOST",
                                "value": args[0].split(":")[0],
                            },
                            {
                                "name": "ZITADEL_DATABASE_POSTGRES_PORT",
                                "value": args[0].split(":")[1],
                            },
                            {
                                "name": "ZITADEL_DATABASE_POSTGRES_USER_USERNAME",
                                "value": DatabaseConstants.MASTER_USERNAME,
                            },
                            {
                                "name": "ZITADEL_DATABASE_POSTGRES_ADMIN_USERNAME",
                                "value": DatabaseConstants.MASTER_USERNAME,
                            },
                            {
                                "name": "ZITADEL_DATABASE_POSTGRES_DATABASE",
                                "value": DatabaseConstants.GLOBAL_DB_NAME,
                            },
                            {
                                "name": "ZITADEL_DATABASE_POSTGRES_ADMIN_SSL_MODE",
                                "value": "require",
                            },
                            {"name": "ZITADEL_DATABASE_POSTGRES_USER_SSL_MODE", "value": "require"},
                            {"name": "ZITADEL_EXTERNALSECURE", "value": "false"},
                            {"name": "ZITADEL_EXTERNALPORT", "value": "80"},
                            {"name": "ZITADEL_EXTERNALDOMAIN", "value": f"identity.{args[10]}"},
                            {"name": "ZITADEL_TLS_ENABLED", "value": "false"},
                            {"name": "ZITADEL_FIRSTINSTANCE_ORG_HUMAN_USERNAME", "value": "admin"},
                            {
                                "name": "ZITADEL_FIRSTINSTANCE_ORG_MACHINE_MACHINE_USERNAME",
                                "value": "pulumi-provisioner",
                            },
                            {
                                "name": "ZITADEL_FIRSTINSTANCE_ORG_MACHINE_MACHINE_NAME",
                                "value": "Pulumi Provisioner",
                            },
                            {
                                "name": "ZITADEL_FIRSTINSTANCE_ORG_MACHINE_MACHINEKEY_TYPE",
                                "value": "1",
                            },
                            {
                                "name": "ZITADEL_FIRSTINSTANCE_PATPATH",
                                "value": "/machinekey/pat.json",
                            },
                            {
                                "name": "ZITADEL_FIRSTINSTANCE_MACHINEKEYPATH",
                                "value": "/machinekey/zitadel-admin-sa.json",
                            },
                        ],
                        "secrets": [
                            {
                                "name": "ZITADEL_DATABASE_POSTGRES_USER_PASSWORD",
                                "valueFrom": f"{args[4]}:password::",
                            },
                            {
                                "name": "ZITADEL_DATABASE_POSTGRES_ADMIN_PASSWORD",
                                "valueFrom": f"{args[4]}:password::",
                            },
                            {
                                "name": "ZITADEL_MASTERKEY",
                                "valueFrom": args[5],
                            },
                            {
                                "name": "ZITADEL_FIRSTINSTANCE_ORG_HUMAN_PASSWORD",
                                "valueFrom": args[9],
                            },
                        ],
                        "logConfiguration": {
                            "logDriver": EcsConstants.LOG_DRIVER,
                            "options": {
                                "awslogs-group": f"/ecs/{prefix}zitadel",
                                "awslogs-region": args[7],
                                "awslogs-stream-prefix": ZitadelConstants.CONTAINER_NAME,
                            },
                        },
                    },
                    {
                        "name": "init-volume",
                        "image": "busybox:latest",
                        "essential": False,
                        "command": ["chown", "-R", "1000:1000", "/machinekey"],
                        "mountPoints": [
                            {"sourceVolume": "machinekey-vol", "containerPath": "/machinekey"}
                        ],
                        "logConfiguration": {
                            "logDriver": EcsConstants.LOG_DRIVER,
                            "options": {
                                "awslogs-group": f"/ecs/{prefix}zitadel",
                                "awslogs-region": args[7],
                                "awslogs-stream-prefix": "init-volume",
                            },
                        },
                    },
                    {
                        "name": "secret-uploader",
                        "image": "amazon/aws-cli:latest",
                        "essential": False,
                        "dependsOn": [{"containerName": "init-volume", "condition": "SUCCESS"}],
                        "entryPoint": ["sh", "-c"],
                        "mountPoints": [
                            {"sourceVolume": "machinekey-vol", "containerPath": "/machinekey"}
                        ],
                        "command": [
                            "echo 'Waiting for Zitadel to generate machine key...'; "
                            "while [ ! -f /machinekey/zitadel-admin-sa.json ]; do sleep 5; done; "
                            "echo 'Machine key found! Uploading to AWS Secrets Manager...'; "
                            f"aws secretsmanager put-secret-value --region {args[7]} --secret-id {args[6]} --secret-string file:///machinekey/zitadel-admin-sa.json; "
                            "echo 'Upload complete. Sidecar exiting.'"
                        ],
                        "logConfiguration": {
                            "logDriver": EcsConstants.LOG_DRIVER,
                            "options": {
                                "awslogs-group": f"/ecs/{prefix}zitadel",
                                "awslogs-region": args[7],
                                "awslogs-stream-prefix": "secret-uploader",
                            },
                        },
                    },
                ]
            )
        ),
        tags=tags,
    )

    zitadel_svc = aws.ecs.Service(
        f"{prefix}zitadel-svc",
        cluster=ecs_cluster_arn,
        task_definition=zitadel_task.arn,
        desired_count=1,
        launch_type=EcsConstants.CAPACITY_PROVIDER,
        enable_execute_command=True,
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
        tags=tags,
    )

    return zitadel_svc
