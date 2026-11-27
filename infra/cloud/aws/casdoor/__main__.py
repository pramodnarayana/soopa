"""
Identity Provider Bounded Context (Casdoor)
===========================================
Provisions the lightweight Apache-2.0 Casdoor OIDC/SSO IdP on AWS ECS Fargate:
- Secrets Manager entries for Admin Password, least-privilege DB Password & DSN, and OAuth M2M creds
- Scoped least-privilege ECS Task & Execution IAM roles (no wildcard CloudWatch log permissions)
- Fargate Task Definition (idempotent least-privilege DB init + Casdoor) + Cloud Map `identity`
- ECS deployment circuit breaker with automatic rollback + Route53 `identity.<domain>` DNS alias
"""

from __future__ import annotations

import pulumi
import pulumi_aws as aws
from constants import CasdoorConstants
from ecs import provision_ecs
from infra_seedwork.constants import LogRetentionPolicy
from roles import provision_roles
from secret_resources import provision_secrets

_env = pulumi.get_stack()
_prefix = f"{_env}-"
_TAGS = {"ManagedBy": "pulumi", "Component": "identity", "Environment": _env}
_region = aws.get_region()
_identity = aws.get_caller_identity()

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
global_db_secret_arn = data.require_output("global_db_secret_arn")

# Secure-by-default governance: 30-day secret recovery & 30-day logs unless overridden in stack config
configured_recovery = config.get_int("secret_recovery_window_days")
secret_recovery_window_days = (
    CasdoorConstants.DEFAULT_SECRET_RECOVERY_WINDOW_DAYS
    if configured_recovery is None
    else configured_recovery
)
configured_retention = config.get_int("log_retention_days")
log_retention_days = (
    LogRetentionPolicy.STANDARD.value if configured_retention is None else configured_retention
)
cpu = config.get("cpu") or CasdoorConstants.DEFAULT_CPU
memory = config.get("memory") or CasdoorConstants.DEFAULT_MEMORY
desired_count = config.get_int("desired_count") or CasdoorConstants.DEFAULT_DESIRED_COUNT
enable_execute_command = config.get_bool("enable_execute_command") or False

secrets_bundle = provision_secrets(
    _prefix,
    _TAGS,
    global_db_endpoint=global_db_endpoint,
    secret_recovery_window_days=secret_recovery_window_days,
)

enable_observability = config.get_bool("enable_observability") or False
firelens_endpoint = obs.require_output("openobserve_endpoint") if enable_observability else None
obs_user_arn = obs.require_output("openobserve_user_secret_arn") if enable_observability else None
obs_pass_arn = (
    obs.require_output("openobserve_password_secret_arn") if enable_observability else None
)

ecs_task_role, ecs_execution_role = provision_roles(
    _prefix,
    _TAGS,
    dsn_secret_arn=secrets_bundle.dsn_secret.arn,
    db_password_secret_arn=secrets_bundle.db_password_secret.arn,
    admin_password_secret_arn=secrets_bundle.admin_password_secret.arn,
    global_db_secret_arn=global_db_secret_arn,
    region_name=_region.name,
    account_id=_identity.account_id,
    enable_execute_command=enable_execute_command,
    obs_user_secret_arn=obs_user_arn,
    obs_password_secret_arn=obs_pass_arn,
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
    dsn_secret_arn=secrets_bundle.dsn_secret.arn,
    db_password_secret_arn=secrets_bundle.db_password_secret.arn,
    global_db_secret_arn=global_db_secret_arn,
    casdoor_ecr_repo_url=casdoor_ecr_repo_url,
    admin_password_secret_arn=secrets_bundle.admin_password_secret.arn,
    ecs_task_role_arn=ecs_task_role.arn,
    ecs_execution_role_arn=ecs_execution_role.arn,
    region_name=_region.name,
    cpu=cpu,
    memory=memory,
    desired_count=desired_count,
    log_retention_days=log_retention_days,
    enable_execute_command=enable_execute_command,
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
            evaluate_target_health=True,
        )
    ],
)

pulumi.export("ecr_repository_url", casdoor_ecr_repo_url)
pulumi.export("identity_service_name", casdoor_svc.name)
pulumi.export("admin_password_secret_arn", secrets_bundle.admin_password_secret.arn)
pulumi.export("admin_oauth_secret_arn", secrets_bundle.admin_oauth_secret.arn)
pulumi.export("platform_realm", CasdoorConstants.PLATFORM_REALM)
pulumi.export("global_realm", CasdoorConstants.GLOBAL_REALM)
pulumi.export("identity_domain", identity_dns_record.name)
