import json

import pulumi
import pulumi_aws as aws


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
    firelens_endpoint: str = None,  # If provided, injects FluentBit sidecar
    queue_arns: list = None,
    topic_arns: list = None,
    bucket_arns: list = None,
    desired_count: int = 1,
    obs_user_secret_arn: str = None,
    obs_password_secret_arn: str = None,
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

    if base_statements:
        aws.iam.RolePolicy(
            f"{name}-task-policy",
            role=task_role.id,
            policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": base_statements,
                }
            ),
        )

    port_mappings = [{"containerPort": port, "hostPort": port}] if port else []
    env_vars = environment_vars if environment_vars else []

    sidecars = []
    if firelens_endpoint:
        sidecars.append(
            {
                "name": "log_router",
                "image": "public.ecr.aws/aws-observability/aws-for-fluent-bit:stable",
                "essential": True,
                "firelensConfiguration": {
                    "type": "fluentbit",
                    "options": {"enable-ecs-log-metadata": "true"},
                },
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-group": f"/ecs/{name}-firelens",
                        "awslogs-region": _region.name,
                        "awslogs-stream-prefix": "fluentbit",
                        "awslogs-create-group": "true",
                    },
                },
            }
        )

    if sidecar_container:
        sidecars.append({**sidecar_container, "image": sidecar_container.get("image")})

    def make_container_defs(args):
        image = args[0]
        env = args[1]
        fl_end = args[2]
        obs_user_arn = args[3]
        obs_pass_arn = args[4]

        main_log_config = {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": f"/ecs/{name}",
                "awslogs-region": _region.name,
                "awslogs-stream-prefix": "app",
                "awslogs-create-group": "true",
            },
        }

        if fl_end:
            host = fl_end.split(":")[0]
            fl_port = fl_end.split(":")[1] if ":" in fl_end else "80"
            main_log_config = {
                "logDriver": "awsfirelens",
                "options": {
                    "Name": "http",
                    "Host": host,
                    "Port": fl_port,
                    "URI": "/api/default/default/_json",
                    "Format": "json",
                    "tls": "on",
                },
                "secretOptions": [
                    {"name": "HTTP_User", "valueFrom": obs_user_arn},
                    {"name": "HTTP_Passwd", "valueFrom": obs_pass_arn},
                ],
            }

        containers = [
            {
                "name": "app",
                "image": image,
                "command": command,
                "essential": True,
                "portMappings": port_mappings,
                "environment": env,
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
        ).apply(make_container_defs),
        volumes=volumes,
        tags=tags,
    )

    # Service
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
        load_balancers=[
            aws.ecs.ServiceLoadBalancerArgs(
                target_group_arn=target_group_arn,
                container_name="app",
                container_port=port,
            )
        ]
        if target_group_arn
        else None,
        tags=tags,
    )

    return svc
