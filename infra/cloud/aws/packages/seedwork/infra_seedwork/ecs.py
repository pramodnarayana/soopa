import json

import pulumi
import pulumi_aws as aws


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


def _build_base_statements(
    queue_arns: list, topic_arns: list, bucket_arns: list, extra_statements: list
) -> list:
    statements = []
    if queue_arns:
        statements.append({"Effect": "Allow", "Action": ["sqs:*"], "Resource": queue_arns})
    if topic_arns:
        statements.append({"Effect": "Allow", "Action": ["sns:*"], "Resource": topic_arns})
    if bucket_arns:
        statements.append({"Effect": "Allow", "Action": ["s3:*"], "Resource": bucket_arns})
    if extra_statements:
        statements.extend(extra_statements)
    return statements


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
            "tls": "off",
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


def provision_fargate_service(  # noqa: C901 - Factory pattern requires high cyclomatic complexity to assemble all AWS ECS primitives in a single atomic transaction
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

    base_statements = _build_base_statements(
        queue_arns, topic_arns, bucket_arns, extra_task_policy_statements
    )

    if enable_execute_command:
        base_statements.append(
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

    port_mappings = [{"containerPort": port, "hostPort": port}] if port else []
    if extra_ports:
        port_mappings.extend([{"containerPort": p, "hostPort": p} for p in extra_ports])
    env_vars = environment_vars if environment_vars else []

    sidecars = []
    if firelens_endpoint:
        sidecars.append(
            build_firelens_sidecar(
                group_name=f"/ecs/{name}",
                region_name=_region.name,
                fluentbit_image_uri=fluentbit_image_uri,
            )
        )

    if sidecar_container:
        sidecars.append({**sidecar_container, "image": sidecar_container.get("image")})

    def make_container_defs(args):
        image = args[0]
        env = args[1]
        fl_end = args[2]
        obs_user_arn = args[3]
        obs_pass_arn = args[4]
        sec = args[5]

        if fl_end:
            main_log_config = build_firelens_log_config(fl_end, obs_user_arn, obs_pass_arn)
        else:
            main_log_config = {
                "logDriver": EcsConstants.LOG_DRIVER_AWSLOGS,
                "options": {
                    "awslogs-group": f"/ecs/{name}",
                    "awslogs-region": _region.name,
                    "awslogs-stream-prefix": EcsConstants.CONTAINER_NAME_APP,
                    "awslogs-create-group": EcsConstants.TRUE_STR,
                },
            }

        containers = [
            {
                "name": EcsConstants.CONTAINER_NAME_APP,
                "image": image,
                "command": command,
                "essential": True,
                "portMappings": port_mappings,
                "environment": env,
                "secrets": sec or [],
                "mountPoints": app_mount_points or [],
                "dependsOn": app_depends_on or [],
                "logConfiguration": main_log_config,
            }
        ]

        for s in sidecars:
            containers.append({**s, "image": image} if not s.get("image") else s)

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

    lbs = []
    if target_group_arn:
        lbs.append(
            aws.ecs.ServiceLoadBalancerArgs(
                target_group_arn=target_group_arn,
                container_name="app",
                container_port=port,
            )
        )
    if extra_target_groups:
        for tg in extra_target_groups:
            lbs.append(
                aws.ecs.ServiceLoadBalancerArgs(
                    target_group_arn=tg["target_group_arn"],
                    container_name="app",
                    container_port=tg["port"],
                )
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
        tags=tags,
    )

    return svc
