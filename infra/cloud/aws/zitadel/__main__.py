"""
Identity Bounded Context
========================
Provisions the Identity layer (Self-Hosted Zitadel):
- ECR Registry Mirror for Zitadel
- Fargate Task Definition (Zitadel + Secret Uploader Sidecar)
- ECS Service
"""

from secrets import provision_secrets

import pulumi
import pulumi_aws as aws
from ecs import provision_ecs
from roles import provision_roles

_env = pulumi.get_stack()
_prefix = f"{_env}-"
_TAGS = {"ManagedBy": "pulumi", "Component": "identity", "Environment": _env}

# ── Stack References ──────────────────────────────────────────────────────────
config = pulumi.Config()
foundation_stack_ref = config.get("foundation_stack") or f"organization/foundation/{_env}"
foundation = pulumi.StackReference(foundation_stack_ref)

platform_stack_ref = config.get("platform_stack") or f"organization/platform/{_env}"
platform = pulumi.StackReference(platform_stack_ref)

data_stack_ref = config.get("data_stack") or f"organization/data/{_env}"
data = pulumi.StackReference(data_stack_ref)

vpc_id = foundation.require_output("vpc_id")
private_subnets = [
    foundation.require_output("private_subnet_a_id"),
    foundation.require_output("private_subnet_b_id"),
]
app_sg_id = foundation.require_output("app_sg_id")

ecs_cluster_arn = platform.require_output("ecs_cluster_arn")
main_listener_arn = platform.require_output("main_alb_listener_arn")
main_alb_dns_name = platform.require_output("main_alb_dns_name")
zitadel_ecr_repo_url = platform.require_output("zitadel_ecr_repo_url")

global_db_endpoint = data.require_output("global_db_endpoint")
global_db_secret_arn = data.require_output("global_db_secret_arn")
global_db_password = data.require_output("global_db_password")

# ── Secrets ───────────────────────────────────────────────────────────────────
masterkey, admin_password, mk_secret, machine_secret, admin_secret = provision_secrets(
    _prefix, _TAGS
)

# ── Roles ─────────────────────────────────────────────────────────────────────
ecs_task_role, ecs_execution_role = provision_roles(
    _prefix, _TAGS, machine_secret.arn, global_db_secret_arn
)

# ── ECS Service & Task ────────────────────────────────────────────────────────
enable_observability = config.get_bool("enable_observability") or False
firelens_endpoint = (
    platform.require_output("openobserve_endpoint") if enable_observability else None
)
obs_user_arn = (
    platform.require_output("openobserve_user_secret_arn") if enable_observability else None
)
obs_pass_arn = (
    platform.require_output("openobserve_password_secret_arn") if enable_observability else None
)

zitadel_svc = provision_ecs(
    prefix=_prefix,
    tags=_TAGS,
    vpc_id=vpc_id,
    private_subnets=private_subnets,
    app_sg_id=app_sg_id,
    ecs_cluster_arn=ecs_cluster_arn,
    cloud_map_namespace_id=platform.require_output("cloud_map_namespace_id"),
    main_listener_arn=main_listener_arn,
    main_alb_dns_name=platform.require_output("staging_domain"),
    global_db_endpoint=global_db_endpoint,
    global_db_password=global_db_password,
    global_db_secret_arn=global_db_secret_arn,
    zitadel_ecr_repo_url=zitadel_ecr_repo_url,
    zitadel_masterkey=masterkey.result,
    zitadel_admin_password=admin_password.result,
    zitadel_masterkey_secret_arn=mk_secret.arn,
    zitadel_machinekey_secret_arn=machine_secret.arn,
    zitadel_admin_password_secret_arn=admin_secret.arn,
    ecs_task_role_arn=ecs_task_role.arn,
    ecs_execution_role_arn=ecs_execution_role.arn,
    firelens_endpoint=firelens_endpoint,
    obs_user_secret_arn=obs_user_arn,
    obs_password_secret_arn=obs_pass_arn,
)

# ── DNS Record ────────────────────────────────────────────────────────────────
staging_domain = platform.require_output("staging_domain")
hosted_zone = aws.route53.get_zone_output(name=staging_domain)
main_alb_dns_name = platform.require_output("main_alb_dns_name")
main_alb_zone_id = platform.require_output("main_alb_zone_id")

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

# ── Exports ───────────────────────────────────────────────────────────────────
pulumi.export("ecr_repository_url", zitadel_ecr_repo_url)
pulumi.export("zitadel_service_name", zitadel_svc.name)
pulumi.export("machinekey_secret_arn", machine_secret.arn)
pulumi.export("identity_domain", identity_dns_record.name)
