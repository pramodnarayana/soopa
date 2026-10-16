import json
from typing import TypedDict

import pulumi
import pulumi_aws as aws


class ContainerDefinition(TypedDict, total=False):
    name: str
    image: str
    command: list[str]
    essential: bool
    portMappings: list[dict[str, object]]
    environment: list[dict[str, object]]
    secrets: list[dict[str, object]]
    mountPoints: list[dict[str, object]]
    dependsOn: list[dict[str, object]]
    logConfiguration: dict[str, object]
    firelensConfiguration: dict[str, object]


class LogConfiguration(TypedDict, total=False):
    logDriver: str
    options: dict[str, str]
    secretOptions: list[dict[str, str]]


class IamPolicyStatement(TypedDict, total=False):
    Sid: str
    Effect: str
    Action: list[str]
    Resource: list[str] | str


class EcsConstants:
    LOG_DRIVER_AWSLOGS = "awslogs"
    LOG_DRIVER_FIRELENS = "awsfirelens"
    FIRELENS_TYPE = "fluentbit"
    CONTAINER_NAME_APP = "app"
    CONTAINER_NAME_LOG_ROUTER = "log_router"
    TRUE_STR = "true"


class ObservabilityConstants:
    DEFAULT_FLUENTBIT_IMAGE = "public.ecr.aws/aws-observability/aws-for-fluent-bit:stable"
    HTTP_OUTPUT_PLUGIN = "http"
    JSON_FORMAT = "json"
    OPENOBSERVE_URI = "/api/default/default/_json"
    DEFAULT_PORT = "80"
    TLS_ON = "off"


def build_task_role_policy_statements(
    queue_arns: list[str] | None = None,
    topic_arns: list[str] | None = None,
    bucket_arns: list[str] | None = None,
    extra_statements: list[dict[str, object]] | None = None,
    enable_execute_command: bool = False,
) -> list[dict[str, object]]:
    """Build IAM statements for ECS task execution role (pure function, zero external dependencies)."""
    statements: list[dict[str, object]] = []
    if queue_arns:
        statements.append({"Effect": "Allow", "Action": ["sqs:*"], "Resource": queue_arns})
    if topic_arns:
        statements.append({"Effect": "Allow", "Action": ["sns:*"], "Resource": topic_arns})
    if bucket_arns:
        statements.append({"Effect": "Allow", "Action": ["s3:*"], "Resource": bucket_arns})
    if extra_statements:
        statements.extend(extra_statements)
    if enable_execute_command:
        statements.append(
            {
                "Sid": "ExecuteCommand",
                "Effect": "Allow",
                "Action": [
                    "ssmmessages:CreateControlChannel",
                    "ssmmessages:CreateDataChannel",
                    "ssmmessages:OpenControlChannel",
                    "ssmmessages:OpenDataChannel",
                ],
                "Resource": "*",
            }
        )
    return statements


def _build_base_statements(
    queue_arns: list, topic_arns: list, bucket_arns: list, extra_statements: list
) -> list:
    """Internal compatibility helper."""
    return build_task_role_policy_statements(
        queue_arns=queue_arns,
        topic_arns=topic_arns,
        bucket_arns=bucket_arns,
        extra_statements=extra_statements,
    )


def build_awslogs_log_config(
    group_name: str,
    region_name: str,
    stream_prefix: str = EcsConstants.CONTAINER_NAME_APP,
) -> LogConfiguration:
    """Build standard CloudWatch awslogs configuration (pure function)."""
    return {
        "logDriver": EcsConstants.LOG_DRIVER_AWSLOGS,
        "options": {
            "awslogs-group": group_name,
            "awslogs-region": region_name,
            "awslogs-stream-prefix": stream_prefix,
            "awslogs-create-group": EcsConstants.TRUE_STR,
        },
    }


def _build_sidecar_definition(s: dict[str, object], fallback_image: str) -> ContainerDefinition:
    """Helper to normalize a sidecar definition dictionary into ContainerDefinition."""
    sidecar_def: ContainerDefinition = {
        "name": str(s.get("name", "")),
        "image": str(s.get("image", fallback_image)),
        "essential": bool(s.get("essential", False)),
    }
    port_mappings = s.get("portMappings")
    if isinstance(port_mappings, list):
        sidecar_def["portMappings"] = port_mappings

    environment = s.get("environment")
    if isinstance(environment, list):
        sidecar_def["environment"] = environment

    secrets = s.get("secrets")
    if isinstance(secrets, list):
        sidecar_def["secrets"] = secrets

    mount_points = s.get("mountPoints")
    if isinstance(mount_points, list):
        sidecar_def["mountPoints"] = mount_points

    depends_on = s.get("dependsOn")
    if isinstance(depends_on, list):
        sidecar_def["dependsOn"] = depends_on

    log_configuration = s.get("logConfiguration")
    if isinstance(log_configuration, dict):
        sidecar_def["logConfiguration"] = log_configuration

    firelens_configuration = s.get("firelensConfiguration")
    if isinstance(firelens_configuration, dict):
        sidecar_def["firelensConfiguration"] = firelens_configuration

    return sidecar_def


def build_container_definitions(
    name: str,
    image: str,
    command: list[str] | None = None,
    container_name: str = EcsConstants.CONTAINER_NAME_APP,
    port_mappings: list[dict[str, object]] | None = None,
    environment: list[dict[str, object]] | None = None,
    secrets: list[dict[str, object]] | None = None,
    mount_points: list[dict[str, object]] | None = None,
    depends_on: list[dict[str, object]] | None = None,
    log_configuration: dict[str, object] | None = None,
    sidecars: list[dict[str, object]] | None = None,
) -> list[ContainerDefinition]:
    """Pure builder for ECS container definitions (zero cloud SDK mocks required)."""
    main_container: ContainerDefinition = {
        "name": container_name,
        "image": image,
        "essential": True,
        "portMappings": port_mappings or [],
        "environment": environment or [],
        "secrets": secrets or [],
        "mountPoints": mount_points or [],
        "dependsOn": depends_on or [],
        "logConfiguration": log_configuration or {},
    }
    if command is not None:
        main_container["command"] = command

    containers: list[ContainerDefinition] = [main_container]
    if sidecars:
        for s in sidecars:
            containers.append(_build_sidecar_definition(s, image))

    return containers


def build_firelens_sidecar(
    group_name: str,
    region_name: str,
    fluentbit_image_uri: str = ObservabilityConstants.DEFAULT_FLUENTBIT_IMAGE,
) -> dict:
    return {
        "name": EcsConstants.CONTAINER_NAME_LOG_ROUTER,
        "image": fluentbit_image_uri,
        "essential": True,
        "firelensConfiguration": {
            "type": EcsConstants.FIRELENS_TYPE,
            "options": {"enable-ecs-log-metadata": EcsConstants.TRUE_STR},
        },
        "logConfiguration": {
            "logDriver": EcsConstants.LOG_DRIVER_AWSLOGS,
            "options": {
                "awslogs-group": f"{group_name}-{EcsConstants.FIRELENS_TYPE}",
                "awslogs-region": region_name,
                "awslogs-stream-prefix": EcsConstants.FIRELENS_TYPE,
                "awslogs-create-group": EcsConstants.TRUE_STR,
            },
        },
    }


def build_firelens_log_config(
    fl_end: str, obs_user_arn: str = None, obs_pass_arn: str = None
) -> dict:
    host = fl_end.split(":")[0]
    fl_port = fl_end.split(":")[1] if ":" in fl_end else ObservabilityConstants.DEFAULT_PORT

    main_log_config = {
        "logDriver": EcsConstants.LOG_DRIVER_FIRELENS,
        "options": {
            "Name": ObservabilityConstants.HTTP_OUTPUT_PLUGIN,
            "Host": host,
            "Port": fl_port,
            "URI": ObservabilityConstants.OPENOBSERVE_URI,
            "Format": ObservabilityConstants.JSON_FORMAT,
            "tls": "on" if str(fl_port) == "443" else "off",
            "tls.verify": "on" if str(fl_port) == "443" else "off",
        },
    }
    if obs_user_arn and obs_pass_arn:
        main_log_config["secretOptions"] = [
            {"name": "http_user", "valueFrom": obs_user_arn},
            {"name": "http_passwd", "valueFrom": obs_pass_arn},
        ]
    elif obs_user_arn or obs_pass_arn:
        raise ValueError(
            "Both obs_user_secret_arn and obs_password_secret_arn must be provided together."
        )
    return main_log_config


def _build_load_balancers(
    port: int | None,
    target_group_arn: str | None,
    extra_target_groups: list[dict[str, object]] | None,
) -> list[aws.ecs.ServiceLoadBalancerArgs]:
    """Helper to assemble ECS service load balancer arguments."""
    lbs: list[aws.ecs.ServiceLoadBalancerArgs] = []
    if target_group_arn and port:
        lbs.append(
            aws.ecs.ServiceLoadBalancerArgs(
                target_group_arn=target_group_arn,
                container_name=EcsConstants.CONTAINER_NAME_APP,
                container_port=port,
            )
        )
    if extra_target_groups:
        for tg in extra_target_groups:
            tg_arn = str(tg.get("target_group_arn", ""))
            tg_port = int(tg.get("port", 0))
            lbs.append(
                aws.ecs.ServiceLoadBalancerArgs(
                    target_group_arn=tg_arn,
                    container_name=EcsConstants.CONTAINER_NAME_APP,
                    container_port=tg_port,
                )
            )
    return lbs


def _build_service_sidecars(
    name: str,
    region_name: str,
    firelens_endpoint: str | None,
    fluentbit_image_uri: str,
    sidecar_container: dict[str, object] | None,
) -> list[dict[str, object]]:
    """Helper to assemble sidecar configurations."""
    sidecars: list[dict[str, object]] = []
    if firelens_endpoint:
        sidecars.append(
            build_firelens_sidecar(
                group_name=f"/ecs/{name}",
                region_name=region_name,
                fluentbit_image_uri=fluentbit_image_uri,
            )
        )
    if sidecar_container:
        sidecars.append({**sidecar_container, "image": sidecar_container.get("image")})
    return sidecars


def provision_fargate_service(
    name: str,
    command: list,
    cluster_arn: str,
    execution_role_arn: str,
    ecr_image_uri: str,
    subnets: list,
    security_group_id: str,
    tags: dict,
    environment_vars: list = None,
    port: int = None,
    is_public: bool = False,
    cpu: str = "512",
    memory: str = "1024",
    sidecar_container: dict = None,
    volumes: list = None,
    app_mount_points: list = None,
    app_depends_on: list = None,
    extra_task_policy_statements: list = None,
    target_group_arn: str = None,
    extra_ports: list = None,
    extra_target_groups: list = None,
    firelens_endpoint: str = None,  # If provided, injects FluentBit sidecar
    fluentbit_image_uri: str = ObservabilityConstants.DEFAULT_FLUENTBIT_IMAGE,
    queue_arns: list = None,
    topic_arns: list = None,
    bucket_arns: list = None,
    desired_count: int = 1,
    obs_user_secret_arn: str = None,
    obs_password_secret_arn: str = None,
    secrets: list = None,
    enable_execute_command: bool = False,
    service_registry_arn: str = None,
) -> aws.ecs.Service:
    """
    Provisions a standard Shopify-style ECS Fargate Service.
    """
    _region = aws.get_region()
    _identity = aws.get_caller_identity()

    # Task Role
    task_role = aws.iam.Role(
        f"{name}-task-role",
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

    base_statements = build_task_role_policy_statements(
        queue_arns=queue_arns,
        topic_arns=topic_arns,
        bucket_arns=bucket_arns,
        extra_statements=extra_task_policy_statements,
        enable_execute_command=enable_execute_command,
    )

    if base_statements:
        aws.iam.RolePolicy(
            f"{name}-task-policy",
            role=task_role.id,
            policy=pulumi.Output.from_input(base_statements).apply(
                lambda resolved_statements: json.dumps(
                    {
                        "Version": "2012-10-17",
                        "Statement": resolved_statements,
                    }
                )
            ),
        )

    port_mappings: list[dict[str, object]] = (
        [{"containerPort": port, "hostPort": port}] if port else []
    )
    if extra_ports:
        for p in extra_ports:
            port_mappings.append({"containerPort": p, "hostPort": p})
    env_vars = environment_vars if environment_vars else []

    sidecars = _build_service_sidecars(
        name=name,
        region_name=_region.name,
        firelens_endpoint=firelens_endpoint,
        fluentbit_image_uri=fluentbit_image_uri,
        sidecar_container=sidecar_container,
    )

    def make_container_defs(args: list[object]) -> str:
        image = str(args[0])
        env = args[1] if isinstance(args[1], list) else []
        fl_end = str(args[2]) if args[2] else None
        obs_user_arn = str(args[3]) if args[3] else None
        obs_pass_arn = str(args[4]) if args[4] else None
        sec = args[5] if isinstance(args[5], list) else []

        main_log_config: LogConfiguration
        if fl_end:
            main_log_config = build_firelens_log_config(fl_end, obs_user_arn, obs_pass_arn)
        else:
            main_log_config = build_awslogs_log_config(
                group_name=f"/ecs/{name}",
                region_name=_region.name,
                stream_prefix=EcsConstants.CONTAINER_NAME_APP,
            )

        containers = build_container_definitions(
            name=name,
            image=image,
            command=command,
            port_mappings=port_mappings,
            environment=env,
            secrets=sec,
            mount_points=app_mount_points,
            depends_on=app_depends_on,
            log_configuration=main_log_config,
            sidecars=sidecars,
        )

        return json.dumps(containers)

    task_def = aws.ecs.TaskDefinition(
        f"{name}-task",
        family=name,
        cpu=cpu,
        memory=memory,
        network_mode="awsvpc",
        requires_compatibilities=["FARGATE"],
        execution_role_arn=execution_role_arn,
        task_role_arn=task_role.arn,
        container_definitions=pulumi.Output.all(
            ecr_image_uri,
            env_vars,
            firelens_endpoint or "",
            obs_user_secret_arn or "",
            obs_password_secret_arn or "",
            secrets or [],
        ).apply(make_container_defs),
        volumes=volumes,
        tags=tags,
    )

    lbs = _build_load_balancers(
        port=port,
        target_group_arn=target_group_arn,
        extra_target_groups=extra_target_groups,
    )

    svc = aws.ecs.Service(
        f"{name}-svc",
        cluster=cluster_arn,
        task_definition=task_def.arn,
        desired_count=desired_count,
        launch_type="FARGATE",
        network_configuration=aws.ecs.ServiceNetworkConfigurationArgs(
            subnets=subnets,
            security_groups=[security_group_id],
            assign_public_ip=is_public,
        ),
        load_balancers=lbs if lbs else None,
        health_check_grace_period_seconds=120 if lbs else None,
        service_registries=aws.ecs.ServiceServiceRegistriesArgs(
            registry_arn=service_registry_arn,
        )
        if service_registry_arn
        else None,
        enable_execute_command=enable_execute_command,
        opts=pulumi.ResourceOptions(ignore_changes=["desired_count"]),
        tags=tags,
    )

    return svc
