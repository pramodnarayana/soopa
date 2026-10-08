import json

import pulumi
import pulumi_aws as aws
from constants import DatabaseConstants, EcsConstants, ZitadelConstants
from infra_seedwork.ecs import build_firelens_log_config, build_firelens_sidecar
from infra_seedwork.network import provision_target_group_and_rule


def provision_ecs(
    prefix,
    tags,
    vpc_id,
    private_subnets,
    app_sg_id,
    ecs_cluster_arn,
    cloud_map_namespace_id,
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
    firelens_endpoint=None,
    obs_user_secret_arn=None,
    obs_password_secret_arn=None,
):

    zitadel_rest_tg = provision_target_group_and_rule(
        name=f"{prefix}zitadel",
        vpc_id=vpc_id,
        listener_arn=main_listener_arn,
        priority=95,
        path_pattern="/*",
        host_header=pulumi.Output.concat("identity.", main_alb_dns_name),
        tags=tags,
        port=ZitadelConstants.PORT,
        health_check_path="/debug/healthz",
        protocol_version="HTTP1",
    )

    zitadel_grpc_tg = provision_target_group_and_rule(
        name=f"{prefix}zitadel-grpc",
        vpc_id=vpc_id,
        listener_arn=main_listener_arn,
        priority=94,  # Higher priority for gRPC
        path_pattern="/*",
        host_header=pulumi.Output.concat("identity.", main_alb_dns_name),
        http_header_name="content-type",
        http_header_values=["application/grpc*"],
        tags=tags,
        port=ZitadelConstants.PORT,
        health_check_path="/debug/healthz",
        health_check_matcher="200",
        protocol_version="HTTP2",
    )

    aws.cloudwatch.LogGroup(
        f"{prefix}zitadel-log-group",
        name=f"/ecs/{prefix}zitadel",
        retention_in_days=3,
        tags=tags,
    )

    def make_container_defs(args):
        db_endpoint = args[0]
        db_secret_arn = args[1]
        masterkey_secret_arn = args[2]
        machinekey_secret_arn = args[3]
        region_name = args[4]
        ecr_repo_url = args[5]
        admin_password_secret_arn = args[6]
        dns_name = args[7]
        fl_end = args[8]
        obs_user_arn = args[9]
        obs_pass_arn = args[10]

        if fl_end:
            main_log_config = build_firelens_log_config(fl_end, obs_user_arn, obs_pass_arn)
        else:
            main_log_config = {
                "logDriver": EcsConstants.LOG_DRIVER,
                "options": {
                    "awslogs-group": f"/ecs/{prefix}zitadel",
                    "awslogs-region": region_name,
                    "awslogs-stream-prefix": ZitadelConstants.CONTAINER_NAME,
                },
            }

        containers = [
            {
                "name": ZitadelConstants.CONTAINER_NAME,
                "image": f"{ecr_repo_url}:{ZitadelConstants.IMAGE.split(':')[-1]}",
                "command": ["start-from-init", "--masterkeyFromEnv"],
                "essential": True,
                "dependsOn": [{"containerName": "init-volume", "condition": "SUCCESS"}],
                "mountPoints": [{"sourceVolume": "machinekey-vol", "containerPath": "/machinekey"}],
                "portMappings": [
                    {
                        "containerPort": ZitadelConstants.PORT,
                        "hostPort": ZitadelConstants.PORT,
                    }
                ],
                "environment": [
                    {"name": "ZITADEL_DATABASE_POSTGRES_HOST", "value": db_endpoint.split(":")[0]},
                    {"name": "ZITADEL_DATABASE_POSTGRES_PORT", "value": db_endpoint.split(":")[1]},
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
                    {"name": "ZITADEL_DATABASE_POSTGRES_ADMIN_SSL_MODE", "value": "require"},
                    {"name": "ZITADEL_DATABASE_POSTGRES_USER_SSL_MODE", "value": "require"},
                    {"name": "ZITADEL_EXTERNALSECURE", "value": "true"},
                    {"name": "ZITADEL_EXTERNALPORT", "value": "443"},
                    {"name": "ZITADEL_EXTERNALDOMAIN", "value": f"identity.{dns_name}"},
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
                    {"name": "ZITADEL_FIRSTINSTANCE_ORG_MACHINE_MACHINEKEY_TYPE", "value": "1"},
                    {"name": "ZITADEL_FIRSTINSTANCE_PATPATH", "value": "/machinekey/pat.json"},
                    {
                        "name": "ZITADEL_FIRSTINSTANCE_MACHINEKEYPATH",
                        "value": "/machinekey/zitadel-admin-sa.json",
                    },
                ],
                "secrets": [
                    {
                        "name": "ZITADEL_DATABASE_POSTGRES_USER_PASSWORD",
                        "valueFrom": f"{db_secret_arn}:password::",
                    },
                    {
                        "name": "ZITADEL_DATABASE_POSTGRES_ADMIN_PASSWORD",
                        "valueFrom": f"{db_secret_arn}:password::",
                    },
                    {"name": "ZITADEL_MASTERKEY", "valueFrom": masterkey_secret_arn},
                    {
                        "name": "ZITADEL_FIRSTINSTANCE_ORG_HUMAN_PASSWORD",
                        "valueFrom": admin_password_secret_arn,
                    },
                ],
                "logConfiguration": main_log_config,
            },
            {
                "name": "init-volume",
                "image": "busybox:latest",
                "essential": False,
                "command": ["chown", "-R", "1000:1000", "/machinekey"],
                "mountPoints": [{"sourceVolume": "machinekey-vol", "containerPath": "/machinekey"}],
                "logConfiguration": {
                    "logDriver": EcsConstants.LOG_DRIVER,
                    "options": {
                        "awslogs-group": f"/ecs/{prefix}zitadel",
                        "awslogs-region": region_name,
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
                "mountPoints": [{"sourceVolume": "machinekey-vol", "containerPath": "/machinekey"}],
                "command": [
                    "echo 'Waiting for Zitadel to generate machine key...'; "
                    "while [ ! -f /machinekey/zitadel-admin-sa.json ]; do sleep 5; done; "
                    "echo 'Machine key found! Uploading to AWS Secrets Manager...'; "
                    f"aws secretsmanager put-secret-value --region {region_name} --secret-id {machinekey_secret_arn} --secret-string file:///machinekey/zitadel-admin-sa.json; "
                    "echo 'Upload complete. Sidecar exiting.'"
                ],
                "logConfiguration": {
                    "logDriver": EcsConstants.LOG_DRIVER,
                    "options": {
                        "awslogs-group": f"/ecs/{prefix}zitadel",
                        "awslogs-region": region_name,
                        "awslogs-stream-prefix": "secret-uploader",
                    },
                },
            },
        ]

        if fl_end:
            containers.append(build_firelens_sidecar(f"/ecs/{prefix}zitadel", region_name))

        return json.dumps(containers)

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
            global_db_secret_arn,
            zitadel_masterkey_secret_arn,
            zitadel_machinekey_secret_arn,
            aws.get_region().name,
            zitadel_ecr_repo_url,
            zitadel_admin_password_secret_arn,
            main_alb_dns_name,
            firelens_endpoint or "",
            obs_user_secret_arn or "",
            obs_password_secret_arn or "",
        ).apply(make_container_defs),
        tags=tags,
    )

    # ── Service Discovery ─────────────────────────────────────────────────────────
    zitadel_sd_service = aws.servicediscovery.Service(
        f"{prefix}zitadel-sd-svc",
        name="zitadel",
        dns_config=aws.servicediscovery.ServiceDnsConfigArgs(
            namespace_id=cloud_map_namespace_id,
            dns_records=[
                aws.servicediscovery.ServiceDnsConfigDnsRecordArgs(
                    ttl=10,
                    type="A",
                )
            ],
            routing_policy="MULTIVALUE",
        ),
        health_check_custom_config=aws.servicediscovery.ServiceHealthCheckCustomConfigArgs(
            failure_threshold=1,
        ),
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
        service_registries=aws.ecs.ServiceServiceRegistriesArgs(
            registry_arn=zitadel_sd_service.arn,
            container_name=ZitadelConstants.CONTAINER_NAME,
        ),
        load_balancers=[
            aws.ecs.ServiceLoadBalancerArgs(
                target_group_arn=zitadel_rest_tg.arn,
                container_name=ZitadelConstants.CONTAINER_NAME,
                container_port=ZitadelConstants.PORT,
            ),
            aws.ecs.ServiceLoadBalancerArgs(
                target_group_arn=zitadel_grpc_tg.arn,
                container_name=ZitadelConstants.CONTAINER_NAME,
                container_port=ZitadelConstants.PORT,
            ),
        ],
        tags=tags,
    )

    return zitadel_svc
