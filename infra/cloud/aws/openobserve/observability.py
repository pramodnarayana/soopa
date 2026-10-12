import json
import os

import pulumi
import pulumi_aws as aws
import pulumi_random as random
from constants import OpenObserveConstants
from infra_seedwork.ecs import provision_fargate_service


def provision_openobserve_foundations(
    prefix: str,
    tags: dict,
    vpc_id: str,
    private_subnets: list[str],
    app_sg_id: str,
    ecs_cluster_arn: str,
    main_listener_arn: str,
    obs_listener_arn: str,
    staging_domain: str,
    cloud_map_namespace_id: str,
    ecr_repository_url: pulumi.Output[str],
):
    obs_bucket = aws.s3.Bucket(
        f"{prefix}observability-data",
        bucket=f"{prefix}observability-data",
        force_destroy=True,
        tags=tags,
    )

    obs_user_password = random.RandomPassword(
        "openobserve-password",
        length=32,
        special=False,
    )

    is_prod = pulumi.get_stack() == "production"

    obs_user_secret = aws.secretsmanager.Secret(
        f"{prefix}obs-user-secret",
        name_prefix=f"platform/{prefix}openobserve-user-",
        recovery_window_in_days=30 if is_prod else 0,
        tags=tags,
    )

    aws.secretsmanager.SecretVersion(
        f"{prefix}obs-user-secret-val",
        secret_id=obs_user_secret.id,
        secret_string=OpenObserveConstants.DEFAULT_ADMIN_EMAIL,
    )

    obs_password_secret = aws.secretsmanager.Secret(
        f"{prefix}obs-password-secret",
        name_prefix=f"platform/{prefix}openobserve-password-",
        recovery_window_in_days=30 if is_prod else 0,
        tags=tags,
    )

    aws.secretsmanager.SecretVersion(
        f"{prefix}obs-password-secret-val",
        secret_id=obs_password_secret.id,
        secret_string=obs_user_password.result,
    )

    # Provision ECS Service for OpenObserve

    obs_tg = aws.lb.TargetGroup(
        f"{prefix}openobserve-tg",
        port=5080,
        protocol="HTTP",
        vpc_id=vpc_id,
        target_type="ip",
        health_check=aws.lb.TargetGroupHealthCheckArgs(
            path="/healthz",
            protocol="HTTP",
            interval=30,
            timeout=5,
            healthy_threshold=2,
            unhealthy_threshold=2,
        ),
        tags=tags,
    )

    aws.lb.ListenerRule(
        f"{prefix}openobserve-obs-rule",
        listener_arn=obs_listener_arn,
        priority=105,
        actions=[aws.lb.ListenerRuleActionArgs(type="forward", target_group_arn=obs_tg.arn)],
        conditions=[
            aws.lb.ListenerRuleConditionArgs(
                path_pattern=aws.lb.ListenerRuleConditionPathPatternArgs(values=["/*"])
            )
        ],
    )

    aws.lb.ListenerRule(
        f"{prefix}openobserve-main-rule",
        listener_arn=main_listener_arn,
        priority=110,
        actions=[aws.lb.ListenerRuleActionArgs(type="forward", target_group_arn=obs_tg.arn)],
        conditions=[
            aws.lb.ListenerRuleConditionArgs(
                host_header=aws.lb.ListenerRuleConditionHostHeaderArgs(
                    values=[pulumi.Output.concat("observability.", staging_domain)]
                )
            )
        ],
    )

    obs_exec_role = aws.iam.Role(
        f"{prefix}obs-exec-role",
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
        f"{prefix}obs-exec-role-attach",
        role=obs_exec_role.name,
        policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
    )
    aws.iam.RolePolicy(
        f"{prefix}obs-exec-role-secrets-policy",
        role=obs_exec_role.id,
        policy=pulumi.Output.all(aws.get_region().name, aws.get_caller_identity().account_id).apply(
            lambda args: json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": ["secretsmanager:GetSecretValue"],
                            "Resource": [
                                f"arn:aws:secretsmanager:{args[0]}:{args[1]}:secret:platform/{prefix}openobserve*",
                            ],
                        }
                    ],
                }
            )
        ),
    )

    aws.cloudwatch.LogGroup(
        f"{prefix}openobserve-log-group",
        name=f"/ecs/{prefix}openobserve",
        retention_in_days=3,
        tags=tags,
    )

    obs_sd = aws.servicediscovery.Service(
        f"{prefix}openobserve-sd",
        name="openobserve",
        dns_config=aws.servicediscovery.ServiceDnsConfigArgs(
            namespace_id=cloud_map_namespace_id,
            dns_records=[aws.servicediscovery.ServiceDnsConfigDnsRecordArgs(ttl=10, type="A")],
            routing_policy="MULTIVALUE",
        ),
        health_check_custom_config=aws.servicediscovery.ServiceHealthCheckCustomConfigArgs(
            failure_threshold=1,
        ),
        tags=tags,
    )

    # Resolve version from versions.env
    openobserve_version = os.environ.get("OPENOBSERVE_VERSION")
    if not openobserve_version:
        env_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../../../../versions.env")
        )
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("OPENOBSERVE_VERSION="):
                        openobserve_version = line.strip().split("=")[1]

    if not openobserve_version:
        openobserve_version = "v0.8.0"

    provision_fargate_service(
        name=f"{prefix}openobserve",
        command=[],
        cluster_arn=ecs_cluster_arn,
        execution_role_arn=obs_exec_role.arn,
        ecr_image_uri=pulumi.Output.concat(ecr_repository_url, f":{openobserve_version}"),
        subnets=private_subnets,
        security_group_id=app_sg_id,
        tags=tags,
        port=5080,
        target_group_arn=obs_tg.arn,
        desired_count=1,
        obs_user_secret_arn=obs_user_secret.arn,
        obs_password_secret_arn=obs_password_secret.arn,
        bucket_arns=[obs_bucket.arn, pulumi.Output.concat(obs_bucket.arn, "/*")],
        environment_vars=[
            {"name": "ZO_DATA_DIR", "value": "/data"},
            {"name": "ZO_S3_BUCKET", "value": obs_bucket.bucket},
            {"name": "ZO_S3_REGION_NAME", "value": aws.get_region().name},
            {"name": "ZO_ROOT_USER_EMAIL", "value": OpenObserveConstants.DEFAULT_ADMIN_EMAIL},
        ],
        secrets=[
            {"name": "ZO_ROOT_USER_PASSWORD", "valueFrom": obs_password_secret.arn},
        ],
        service_registry_arn=obs_sd.arn,
    )

    return obs_bucket, obs_user_secret.arn, obs_password_secret.arn
