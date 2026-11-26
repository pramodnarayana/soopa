"""Single-container lightweight Casdoor ECS Fargate service and ALB target group."""

from __future__ import annotations

import json

import pulumi
import pulumi_aws as aws
from constants import CasdoorConstants, EcsConstants
from infra_seedwork.ecs import (
    ContainerDefinition,
    build_awslogs_log_config,
    build_firelens_log_config,
    build_firelens_sidecar,
)
from infra_seedwork.network import provision_target_group_and_rule


def provision_ecs(
    *,
    prefix: str,
    tags: dict[str, str],
    vpc_id: pulumi.Input[str],
    private_subnets: list[pulumi.Input[str]],
    app_sg_id: pulumi.Input[str],
    ecs_cluster_arn: pulumi.Input[str],
    cloud_map_namespace_id: pulumi.Input[str],
    main_listener_arn: pulumi.Input[str],
    staging_domain: pulumi.Input[str],
    dsn_secret_arn: pulumi.Input[str],
    casdoor_ecr_repo_url: pulumi.Input[str],
    admin_password_secret_arn: pulumi.Input[str],
    ecs_task_role_arn: pulumi.Input[str],
    ecs_execution_role_arn: pulumi.Input[str],
    firelens_endpoint: pulumi.Input[str] | None = None,
    obs_user_secret_arn: pulumi.Input[str] | None = None,
    obs_password_secret_arn: pulumi.Input[str] | None = None,
) -> aws.ecs.Service:
    casdoor_tg = provision_target_group_and_rule(
        name=f"{prefix}casdoor",
        vpc_id=vpc_id,
        listener_arn=main_listener_arn,
        priority=95,
        path_pattern="/*",
        host_header=pulumi.Output.concat("identity.", staging_domain),
        tags=tags,
        port=CasdoorConstants.PORT,
        health_check_path=CasdoorConstants.HEALTH_CHECK_PATH,
        protocol_version="HTTP1",
    )

    aws.cloudwatch.LogGroup(
        f"{prefix}casdoor-log-group",
        name=f"/ecs/{prefix}casdoor",
        retention_in_days=7,
        tags=tags,
    )

    def make_container_defs(args: list[str]) -> str:
        (
            dsn_arn,
            region_name,
            ecr_repo_url,
            admin_pwd_arn,
            dns_domain,
            fl_end,
            obs_user_arn,
            obs_pass_arn,
        ) = args

        if fl_end:
            main_log_config = build_firelens_log_config(fl_end, obs_user_arn, obs_pass_arn)
        else:
            main_log_config = build_awslogs_log_config(
                group_name=f"/ecs/{prefix}casdoor",
                region_name=region_name,
                stream_prefix=CasdoorConstants.CONTAINER_NAME,
            )

        image_tag = CasdoorConstants.IMAGE.split(":")[-1]
        containers: list[ContainerDefinition] = [
            {
                "name": CasdoorConstants.CONTAINER_NAME,
                "image": f"{ecr_repo_url}:{image_tag}",
                "essential": True,
                "portMappings": [
                    {
                        "containerPort": CasdoorConstants.PORT,
                        "hostPort": CasdoorConstants.PORT,
                    }
                ],
                "environment": [
                    {"name": "RUNNING_IN_DOCKER", "value": "true"},
                    {"name": "httpport", "value": str(CasdoorConstants.PORT)},
                    {"name": "driverName", "value": "postgres"},
                    {"name": "dbName", "value": CasdoorConstants.DB_NAME},
                    {"name": "origin", "value": f"https://identity.{dns_domain}"},
                    {"name": "originFrontend", "value": f"https://identity.{dns_domain}"},
                ],
                "secrets": [
                    {"name": "dataSourceName", "valueFrom": dsn_arn},
                    {"name": "initAdminPassword", "valueFrom": admin_pwd_arn},
                ],
                "logConfiguration": main_log_config,
            }
        ]

        if fl_end:
            containers.append(build_firelens_sidecar(f"/ecs/{prefix}casdoor", region_name))

        return json.dumps(containers)

    casdoor_task = aws.ecs.TaskDefinition(
        f"{prefix}casdoor-task",
        family=f"{prefix}casdoor",
        cpu=CasdoorConstants.CPU,
        memory=CasdoorConstants.MEMORY,
        network_mode="awsvpc",
        requires_compatibilities=[EcsConstants.CAPACITY_PROVIDER],
        execution_role_arn=ecs_execution_role_arn,
        task_role_arn=ecs_task_role_arn,
        container_definitions=pulumi.Output.all(
            dsn_secret_arn,
            aws.get_region().name,
            casdoor_ecr_repo_url,
            admin_password_secret_arn,
            staging_domain,
            firelens_endpoint or "",
            obs_user_secret_arn or "",
            obs_password_secret_arn or "",
        ).apply(make_container_defs),
        tags=tags,
    )

    identity_sd_service = aws.servicediscovery.Service(
        f"{prefix}identity-sd-svc",
        name="identity",
        dns_config=aws.servicediscovery.ServiceDnsConfigArgs(
            namespace_id=cloud_map_namespace_id,
            dns_records=[aws.servicediscovery.ServiceDnsConfigDnsRecordArgs(ttl=10, type="A")],
            routing_policy="MULTIVALUE",
        ),
        health_check_custom_config=aws.servicediscovery.ServiceHealthCheckCustomConfigArgs(
            failure_threshold=1,
        ),
    )

    return aws.ecs.Service(
        f"{prefix}casdoor-svc",
        cluster=ecs_cluster_arn,
        task_definition=casdoor_task.arn,
        desired_count=1,
        launch_type=EcsConstants.CAPACITY_PROVIDER,
        enable_execute_command=True,
        network_configuration=aws.ecs.ServiceNetworkConfigurationArgs(
            subnets=private_subnets,
            security_groups=[app_sg_id],
            assign_public_ip=False,
        ),
        service_registries=aws.ecs.ServiceServiceRegistriesArgs(
            registry_arn=identity_sd_service.arn,
            container_name=CasdoorConstants.CONTAINER_NAME,
        ),
        load_balancers=[
            aws.ecs.ServiceLoadBalancerArgs(
                target_group_arn=casdoor_tg.arn,
                container_name=CasdoorConstants.CONTAINER_NAME,
                container_port=CasdoorConstants.PORT,
            )
        ],
        opts=pulumi.ResourceOptions(ignore_changes=["desired_count"]),
        tags=tags,
    )
