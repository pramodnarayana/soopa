import json

import pulumi
import pulumi_aws as aws


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
    desired_count: int = 1,
) -> aws.ecs.Service:
    """
    Provisions a standard Shopify-style ECS Fargate Service.
    """
    _region = aws.get_region()

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

    # Basic permissions for SQS, SNS, S3
    base_statements = [
        {
            "Effect": "Allow",
            "Action": [
                "sqs:*",
                "sns:*",
                "s3:*",
            ],
            "Resource": "*",
        }
    ]
    if extra_task_policy_statements:
        base_statements.extend(extra_task_policy_statements)

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

    # Setup FireLens Sidecar and Log Configuration
    sidecars = []
    log_configuration = {
        "logDriver": "awslogs",
        "options": {
            "awslogs-group": f"/ecs/{name}",
            "awslogs-region": _region.name,
            "awslogs-stream-prefix": "app",
            "awslogs-create-group": "true",
        },
    }

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
        log_configuration = {
            "logDriver": "awsfirelens",
            "options": {
                "Name": "http",
                "Host": firelens_endpoint.split(":")[0],
                "Port": firelens_endpoint.split(":")[1] if ":" in firelens_endpoint else "80",
                "URI": "/api/default/default/_json",
                "HTTP_User": "admin@example.com",
                "HTTP_Passwd": "ComplexPassword123!",
                "Format": "json",
            },
        }

    if sidecar_container:
        # In a real app we'd map this better, but assuming sidecar_container needs the app image if no image provided
        sidecars.append({**sidecar_container, "image": sidecar_container.get("image")})

    task_def = aws.ecs.TaskDefinition(
        f"{name}-task",
        family=name,
        cpu=cpu,
        memory=memory,
        network_mode="awsvpc",
        requires_compatibilities=["FARGATE"],
        execution_role_arn=execution_role_arn,
        task_role_arn=task_role.arn,
        container_definitions=pulumi.Output.all(ecr_image_uri, env_vars).apply(
            lambda args: json.dumps(
                [
                    {
                        "name": "app",
                        "image": args[0],
                        "command": command,
                        "essential": True,
                        "portMappings": port_mappings,
                        "environment": args[1],
                        "mountPoints": app_mount_points or [],
                        "dependsOn": app_depends_on or [],
                        "logConfiguration": log_configuration,
                    }
                ]
                + [{**s, "image": args[0]} if not s.get("image") else s for s in sidecars]
            )
        ),
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
