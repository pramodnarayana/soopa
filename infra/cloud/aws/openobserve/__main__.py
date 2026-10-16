"""
Observability Layer (Shared Software)
=====================================
Provisions the OpenObserve stack onto the ECS platform.
"""

import pulumi
import pulumi_aws as aws
from constants import OpenObserveConstants
from observability import provision_openobserve_foundations

_env = pulumi.get_stack()
_prefix = f"{_env}-"
_TAGS = {"ManagedBy": "pulumi", "Component": "openobserve", "Environment": _env}

config = pulumi.Config()
enable_observability = config.get_bool("enable")

if enable_observability is not False:
    # ── Stack References ──────────────────────────────────────────────────────────
    foundation_stack_ref = config.get("foundation_stack") or f"organization/foundation/{_env}"
    foundation = pulumi.StackReference(foundation_stack_ref)

    platform_stack_ref = config.get("platform_stack") or f"organization/platform/{_env}"
    platform = pulumi.StackReference(platform_stack_ref)

    vpc_id = foundation.require_output("vpc_id")
    private_subnets = [
        foundation.require_output("private_subnet_a_id"),
        foundation.require_output("private_subnet_b_id"),
    ]
    app_sg_id = foundation.require_output("app_sg_id")

    ecs_cluster_arn = platform.require_output("ecs_cluster_arn")
    main_listener_arn = platform.require_output("main_alb_listener_arn")
    obs_listener_arn = platform.require_output("main_alb_obs_listener_arn")
    cloud_map_namespace_id = platform.require_output("cloud_map_namespace_id")
    cloud_map_namespace_name = platform.require_output("cloud_map_namespace_name")
    staging_domain = platform.require_output("staging_domain")
    openobserve_ecr_repo_url = platform.require_output("openobserve_ecr_repo_url")

    retention_days = config.get_int("log_retention_days")
    if retention_days is None:
        is_prod = _env == "production"
        retention_days = (
            OpenObserveConstants.DEFAULT_PROD_RETENTION_DAYS
            if is_prod
            else OpenObserveConstants.DEFAULT_NON_PROD_RETENTION_DAYS
        )

    # ── Provision OpenObserve ─────────────────────────────────────────────────────
    obs_bucket, obs_user_arn, obs_pass_arn = provision_openobserve_foundations(
        prefix=_prefix,
        tags=_TAGS,
        vpc_id=vpc_id,
        private_subnets=private_subnets,
        app_sg_id=app_sg_id,
        ecs_cluster_arn=ecs_cluster_arn,
        main_listener_arn=main_listener_arn,
        obs_listener_arn=obs_listener_arn,
        staging_domain=staging_domain,
        cloud_map_namespace_id=cloud_map_namespace_id,
        ecr_repository_url=openobserve_ecr_repo_url,
        retention_days=retention_days,
    )

    hosted_zone = aws.route53.get_zone_output(name=staging_domain)
    obs_dns_record = aws.route53.Record(
        f"{_prefix}observability-dns",
        zone_id=hosted_zone.id,
        name=pulumi.Output.concat("observability.", staging_domain),
        type="A",
        aliases=[
            aws.route53.RecordAliasArgs(
                name=platform.require_output("main_alb_dns_name"),
                zone_id=platform.require_output("main_alb_zone_id"),
                evaluate_target_health=False,
            )
        ],
    )

    # Cost optimization: Internal Cloud Map endpoint for ECS log shippers (0 NAT/ALB fees)
    internal_log_endpoint = cloud_map_namespace_name.apply(lambda ns: f"openobserve.{ns}:5080")
    pulumi.export("openobserve_endpoint", internal_log_endpoint)
    pulumi.export("openobserve_ui_url", pulumi.Output.concat("https://", obs_dns_record.name))
    pulumi.export("openobserve_user_secret_arn", obs_user_arn)
    pulumi.export("openobserve_password_secret_arn", obs_pass_arn)
    pulumi.export("openobserve_bucket_name", obs_bucket.bucket)
    pulumi.export("openobserve_bucket_arn", obs_bucket.arn)
