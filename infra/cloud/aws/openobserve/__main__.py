"""
Observability Layer (Shared Software)
=====================================
Provisions the OpenObserve stack onto the ECS platform.
"""

import pulumi
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
    staging_domain = platform.require_output("staging_domain")

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
    )

    import pulumi_aws as aws

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

    pulumi.export("openobserve_endpoint", obs_dns_record.name.apply(lambda dns: f"{dns}:443"))
    pulumi.export("openobserve_user_secret_arn", obs_user_arn)
    pulumi.export("openobserve_password_secret_arn", obs_pass_arn)
    pulumi.export("openobserve_bucket_name", obs_bucket.bucket)
    pulumi.export("openobserve_bucket_arn", obs_bucket.arn)
