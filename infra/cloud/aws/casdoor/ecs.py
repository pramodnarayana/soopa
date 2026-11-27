"""Lightweight Casdoor ECS Fargate service, least-privilege DB init container, and ALB routing."""

from __future__ import annotations

import json

import pulumi
import pulumi_aws as aws
from constants import CasdoorConstants, EcsConstants, resolve_casdoor_version
from infra_seedwork.constants import DatabaseConstants, LogRetentionPolicy, validate_log_retention
from infra_seedwork.ecs import (
    ContainerDefinition,
    build_awslogs_log_config,
    build_firelens_log_config,
    build_firelens_sidecar,
)
from infra_seedwork.network import provision_target_group_and_rule

# Single atomic stdin psql bootstrap using native :'var' interpolation and format('%I'/'%L', ...).
# Note: psql NEVER expands :var inside `-c`, so SQL MUST be piped over stdin.
# Grants `casdoor_app` to `current_user` first to satisfy AWS RDS PostgreSQL 15+ OWNER rules,
# creates/rotates the non-superuser `casdoor_app` role, creates the isolated `casdoor` database,
# and revokes PUBLIC/casdoor_app CONNECT access on `global_db`.
DB_INIT_SHELL_COMMAND: str = (
    "printf '%s\\n' "
    "\"SELECT format('CREATE ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'db_user', :'db_pass') "
    "WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'db_user')\\gexec\" "
    "\"SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L NOCREATEDB NOCREATEROLE', :'db_user', :'db_pass')\\gexec\" "
    "\"SELECT format('GRANT %I TO %I', :'db_user', current_user)\\gexec\" "
    "\"SELECT format('CREATE DATABASE %I OWNER %I', :'db_name', :'db_user') "
    "WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db_name')\\gexec\" "
    "\"SELECT format('ALTER DATABASE %I OWNER TO %I', :'db_name', :'db_user')\\gexec\" "
    "\"SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'db_name')\\gexec\" "
    "\"SELECT format('GRANT ALL PRIVILEGES ON DATABASE %I TO %I', :'db_name', :'db_user')\\gexec\" "
    "\"SELECT format('REVOKE ALL ON DATABASE %I FROM %I', :'global_db_name', :'db_user')\\gexec\" "
    "\"SELECT format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', :'global_db_name')\\gexec\" "
    "| psql -v ON_ERROR_STOP=1 "
    '-v db_name="$CASDOOR_DB_NAME" '
    '-v db_user="$CASDOOR_DB_USER" '
    '-v db_pass="$CASDOOR_DB_PASSWORD" '
    '-v global_db_name="$GLOBAL_DB_NAME"'
)


def build_casdoor_container_definitions(
    *,
    prefix: str,
    dsn_arn: str,
    db_password_arn: str,
    global_db_arn: str,
    region_name: str,
    ecr_repo_url: str,
    image_tag: str,
    dns_domain: str,
    firelens_endpoint: str = "",
    obs_user_arn: str = "",
    obs_pass_arn: str = "",
) -> list[ContainerDefinition]:
    """Build ECS Fargate container definitions for Casdoor DB init, app, and optional FireLens."""
    init_log_config = build_awslogs_log_config(
        group_name=f"/ecs/{prefix}casdoor",
        region_name=region_name,
        stream_prefix=CasdoorConstants.DB_INIT_CONTAINER_NAME,
    )
    if firelens_endpoint:
        main_log_config = build_firelens_log_config(
            firelens_endpoint, obs_user_arn or None, obs_pass_arn or None
        )
    else:
        main_log_config = build_awslogs_log_config(
            group_name=f"/ecs/{prefix}casdoor",
            region_name=region_name,
            stream_prefix=CasdoorConstants.CONTAINER_NAME,
        )

    containers: list[ContainerDefinition] = [
        {
            "name": CasdoorConstants.DB_INIT_CONTAINER_NAME,
            "image": CasdoorConstants.DB_INIT_IMAGE,
            "essential": False,
            "command": ["sh", "-c", DB_INIT_SHELL_COMMAND],
            "environment": [
                {"name": "PGDATABASE", "value": "postgres"},
                {"name": "PGSSLMODE", "value": "require"},
                {"name": "CASDOOR_DB_NAME", "value": CasdoorConstants.DB_NAME},
                {"name": "CASDOOR_DB_USER", "value": CasdoorConstants.DB_USER},
                {"name": "GLOBAL_DB_NAME", "value": DatabaseConstants.GLOBAL_DB_NAME},
            ],
            "secrets": [
                {"name": "PGHOST", "valueFrom": f"{global_db_arn}:host::"},
                {"name": "PGPORT", "valueFrom": f"{global_db_arn}:port::"},
                {"name": "PGUSER", "valueFrom": f"{global_db_arn}:username::"},
                {"name": "PGPASSWORD", "valueFrom": f"{global_db_arn}:password::"},
                {"name": "CASDOOR_DB_PASSWORD", "valueFrom": db_password_arn},
            ],
            "logConfiguration": init_log_config,
        },
        {
            "name": CasdoorConstants.CONTAINER_NAME,
            "image": f"{ecr_repo_url}:{image_tag}",
            "essential": True,
            "dependsOn": [
                {
                    "containerName": CasdoorConstants.DB_INIT_CONTAINER_NAME,
                    "condition": "SUCCESS",
                }
            ],
            "portMappings": [
                {
                    "containerPort": CasdoorConstants.PORT,
                    "hostPort": CasdoorConstants.PORT,
                }
            ],
            "environment": [
                {"name": "RUNNING_IN_DOCKER", "value": "true"},
                {"name": "BEEGO_RUNMODE", "value": "prod"},
                {"name": "driverName", "value": "postgres"},
                {"name": "dbName", "value": CasdoorConstants.DB_NAME},
                {"name": "origin", "value": f"https://identity.{dns_domain}"},
                {"name": "originFrontend", "value": f"https://identity.{dns_domain}"},
            ],
            "secrets": [
                {"name": "dataSourceName", "valueFrom": dsn_arn},
            ],
            "logConfiguration": main_log_config,
        },
    ]

    if firelens_endpoint:
        containers.append(build_firelens_sidecar(f"/ecs/{prefix}casdoor", region_name))

    return containers


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
    db_password_secret_arn: pulumi.Input[str],
    global_db_secret_arn: pulumi.Input[str],
    casdoor_ecr_repo_url: pulumi.Input[str],
    ecs_task_role_arn: pulumi.Input[str],
    ecs_execution_role_arn: pulumi.Input[str],
    region_name: str,
    cpu: str = CasdoorConstants.DEFAULT_CPU,
    memory: str = CasdoorConstants.DEFAULT_MEMORY,
    desired_count: int = CasdoorConstants.DEFAULT_DESIRED_COUNT,
    log_retention_days: int = LogRetentionPolicy.STANDARD.value,
    enable_execute_command: bool = False,
    firelens_endpoint: pulumi.Input[str] | None = None,
    obs_user_secret_arn: pulumi.Input[str] | None = None,
    obs_password_secret_arn: pulumi.Input[str] | None = None,
) -> aws.ecs.Service:
    image_tag = resolve_casdoor_version()
    validated_retention = validate_log_retention(log_retention_days)

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
        retention_in_days=validated_retention,
        tags=tags,
    )
    if firelens_endpoint is not None:
        aws.cloudwatch.LogGroup(
            f"{prefix}casdoor-firelens-log-group",
            name=f"/ecs/{prefix}casdoor-firelens",
            retention_in_days=validated_retention,
            tags=tags,
        )

    def make_container_defs(args: list[str]) -> str:
        return json.dumps(
            build_casdoor_container_definitions(
                prefix=prefix,
                dsn_arn=args[0],
                db_password_arn=args[1],
                global_db_arn=args[2],
                region_name=region_name,
                ecr_repo_url=args[3],
                image_tag=image_tag,
                dns_domain=args[4],
                firelens_endpoint=args[5],
                obs_user_arn=args[6],
                obs_pass_arn=args[7],
            )
        )

    casdoor_task = aws.ecs.TaskDefinition(
        f"{prefix}casdoor-task",
        family=f"{prefix}casdoor",
        cpu=cpu,
        memory=memory,
        network_mode="awsvpc",
        requires_compatibilities=[EcsConstants.CAPACITY_PROVIDER],
        execution_role_arn=ecs_execution_role_arn,
        task_role_arn=ecs_task_role_arn,
        container_definitions=pulumi.Output.all(
            dsn_secret_arn,
            db_password_secret_arn,
            global_db_secret_arn,
            casdoor_ecr_repo_url,
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
        desired_count=desired_count,
        launch_type=EcsConstants.CAPACITY_PROVIDER,
        enable_execute_command=enable_execute_command,
        wait_for_steady_state=True,
        health_check_grace_period_seconds=CasdoorConstants.HEALTH_CHECK_GRACE_PERIOD_SECONDS,
        deployment_circuit_breaker=aws.ecs.ServiceDeploymentCircuitBreakerArgs(
            enable=True,
            rollback=True,
        ),
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
