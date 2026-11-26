"""
Identity Provider Bounded Context (Casdoor)
===========================================
Provisions the lightweight Apache-2.0 Casdoor OIDC/SSO IdP on AWS ECS Fargate:
- Secrets Manager entries for Admin Password, PostgreSQL DSN, & M2M Admin OAuth credentials
- Least-privilege ECS Task & Execution IAM roles
- Single-container Fargate Task Definition (256 CPU / 512 MB RAM) + Cloud Map `identity`
- Route53 `identity.<domain>` DNS alias
"""

from __future__ import annotations

from secrets import provision_secrets

import pulumi
import pulumi_aws as aws
from ecs import provision_ecs
from roles import provision_roles

_env = pulumi.get_stack()
_prefix = f"{_env}-"
_TAGS = {"ManagedBy": "pulumi", "Component": "identity", "Environment": _env}

config = pulumi.Config()
foundation = pulumi.StackReference(
    config.get("foundation_stack") or f"organization/foundation/{_env}"
)
platform = pulumi.StackReference(config.get("platform_stack") or f"organization/platform/{_env}")
data = pulumi.StackReference(config.get("data_stack") or f"organization/data/{_env}")
obs = pulumi.StackReference(
    config.get("openobserve_stack") or f"organization/organization-openobserve/{_env}"
)

vpc_id = foundation.require_output("vpc_id")
private_subnets = [
    foundation.require_output("private_subnet_a_id"),
    foundation.require_output("private_subnet_b_id"),
]
app_sg_id = foundation.require_output("app_sg_id")

ecs_cluster_arn = platform.require_output("ecs_cluster_arn")
main_listener_arn = platform.require_output("main_alb_listener_arn")
staging_domain = platform.require_output("staging_domain")
main_alb_dns_name = platform.require_output("main_alb_dns_name")
main_alb_zone_id = platform.require_output("main_alb_zone_id")
casdoor_ecr_repo_url = platform.require_output("casdoor_ecr_repo_url")

global_db_endpoint = data.require_output("global_db_endpoint")
global_db_password = data.require_output("global_db_password")

secret_recovery_window_days = config.get_int("secret_recovery_window_days") or 0
_, admin_password_secret, dsn_secret, admin_oauth_secret = provision_secrets(
    _prefix,
    _TAGS,
    global_db_endpoint=global_db_endpoint,
    global_db_password=global_db_password,
    secret_recovery_window_days=secret_recovery_window_days,
)

ecs_task_role, ecs_execution_role = provision_roles(
    _prefix, _TAGS, dsn_secret.arn, admin_password_secret.arn
)

enable_observability = config.get_bool("enable_observability") or False
firelens_endpoint = obs.require_output("openobserve_endpoint") if enable_observability else None
obs_user_arn = obs.require_output("openobserve_user_secret_arn") if enable_observability else None
obs_pass_arn = (
    obs.require_output("openobserve_password_secret_arn") if enable_observability else None
)

casdoor_svc = provision_ecs(
    prefix=_prefix,
    tags=_TAGS,
    vpc_id=vpc_id,
    private_subnets=private_subnets,
    app_sg_id=app_sg_id,
    ecs_cluster_arn=ecs_cluster_arn,
    cloud_map_namespace_id=platform.require_output("cloud_map_namespace_id"),
    main_listener_arn=main_listener_arn,
    staging_domain=staging_domain,
    dsn_secret_arn=dsn_secret.arn,
    casdoor_ecr_repo_url=casdoor_ecr_repo_url,
    admin_password_secret_arn=admin_password_secret.arn,
    ecs_task_role_arn=ecs_task_role.arn,
    ecs_execution_role_arn=ecs_execution_role.arn,
    firelens_endpoint=firelens_endpoint,
    obs_user_secret_arn=obs_user_arn,
    obs_password_secret_arn=obs_pass_arn,
)

hosted_zone = aws.route53.get_zone_output(name=staging_domain)
identity_dns_record = aws.route53.Record(
    f"{_prefix}identity-dns",
    zone_id=hosted_zone.id,
    name=pulumi.Output.concat("identity.", staging_domain),
    type="A",
    aliases=[
        aws.route53.RecordAliasArgs(
            name=main_alb_dns_name,
            zone_id=main_alb_zone_id,
            evaluate_target_health=False,
        )
    ],
)

pulumi.export("ecr_repository_url", casdoor_ecr_repo_url)
pulumi.export("identity_service_name", casdoor_svc.name)
pulumi.export("admin_password_secret_arn", admin_password_secret.arn)
pulumi.export("admin_oauth_secret_arn", admin_oauth_secret.arn)
pulumi.export("platform_realm", "soopa-platform")
pulumi.export("global_realm", "soopa-global")
pulumi.export("identity_domain", identity_dns_record.name)
