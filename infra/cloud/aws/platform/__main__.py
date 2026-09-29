"""
Platform Shared Services Layer (Layer 3)
========================================
Provisions core components used by all bounded contexts:
- ECS Fargate Cluster
- Application Load Balancer
- Observability (CloudWatch, OpenObserve)
"""

import pulumi
import pulumi_aws as aws
from alb import provision_load_balancer
from ecr import provision_ecr
from ecs_cluster import provision_cluster
from event_bus import provision_event_bus
from observability import provision_openobserve

_env = pulumi.get_stack()
_prefix = f"{_env}-"
_TAGS = {"ManagedBy": "pulumi", "Component": "platform", "Environment": _env}

# ── Stack Reference to Foundation ─────────────────────────────────────────────
config = pulumi.Config()
foundation_stack_ref = config.get("foundation_stack") or f"organization/foundation/{_env}"
foundation = pulumi.StackReference(foundation_stack_ref)

vpc_id = foundation.require_output("vpc_id")
public_subnets = [
    foundation.require_output("public_subnet_a_id"),
    foundation.require_output("public_subnet_b_id"),
]
private_subnets = [
    foundation.require_output("private_subnet_a_id"),
    foundation.require_output("private_subnet_b_id"),
]
app_sg_id = foundation.require_output("app_sg_id")
main_alb_sg_id = foundation.require_output("main_alb_sg_id")


# ── Dynamic Certificate Lookup & Domain ───────────────────────────────────────
root_domain = config.require("root_domain")
staging_domain = config.require("staging_domain")

# Dynamically find the Issued certificate for our domain (no hardcoded ARNs!)
cert = aws.acm.get_certificate(domain=root_domain, most_recent=True, statuses=["ISSUED"])

# ── Application Load Balancer ─────────────────────────────────────────────────
main_alb, main_listener, obs_listener = provision_load_balancer(
    prefix=_prefix,
    subnets=public_subnets,
    sg_id=main_alb_sg_id,
    tags=_TAGS,
    cert_arn=cert.arn,
)

# ── ECS Cluster ───────────────────────────────────────────────────────────────
ecs_cluster = provision_cluster(prefix=_prefix, tags=_TAGS)

# ── Observability ─────────────────────────────────────────────────────────────
enable_observability = config.get_bool("enable_observability")
if enable_observability:
    obs_count = config.get_int("openobserve_desired_count") or 1
    obs_svc = provision_openobserve(
        prefix=_prefix,
        tags=_TAGS,
        vpc_id=vpc_id,
        private_subnets=private_subnets,
        app_sg_id=app_sg_id,
        ecs_cluster_arn=ecs_cluster.arn,
        obs_listener_arn=obs_listener.arn,
        obs_count=obs_count,
    )

# ── Universal Event Bus (Messaging) ───────────────────────────────────────────
platform_events_topic = provision_event_bus(prefix=_prefix, tags=_TAGS)

# ── Container Registries ──────────────────────────────────────────────────────
zitadel_ecr_repo, app_ecr_repo, debezium_ecr_repo = provision_ecr(prefix=_prefix, tags=_TAGS)

# ── App Defaults Secret ───────────────────────────────────────────────────────
# Stores application-level shared credentials that must NOT be injected as
# plaintext ECS environment variables. Compute stacks reference the exported
# ARN and inject via ECS secrets (Secrets Manager at runtime), keeping values
# out of the AWS Console task definition view and Pulumi state files.
#
# The password value is read securely from AWS SSM Parameter Store at deploy time.
# Ops must create this parameter out-of-band once:
#   aws ssm put-parameter --name "/{_env}/platform/identity_default_user_password" \
#     --value "Password1!" --type SecureString
identity_pwd_param = aws.ssm.get_parameter_output(
    name=f"/{_env}/platform/identity_default_user_password",
    with_decryption=True,
)
identity_default_user_password = pulumi.Output.secret(identity_pwd_param.value)

app_defaults_secret = aws.secretsmanager.Secret(
    f"{_prefix}app-defaults",
    name=f"{_prefix}app-defaults",
    description="Shared application-level credentials for platform workers (e.g. identity seed password).",
    tags=_TAGS,
)
aws.secretsmanager.SecretVersion(
    f"{_prefix}app-defaults-version",
    secret_id=app_defaults_secret.id,
    secret_string=identity_default_user_password.apply(
        lambda pwd: f'{{"identity_default_user_password":"{pwd}"}}'
    ),
)

# ── Exports ───────────────────────────────────────────────────────────────────
pulumi.export("ecs_cluster_arn", ecs_cluster.arn)
pulumi.export("ecs_cluster_name", ecs_cluster.name)
pulumi.export("main_alb_listener_arn", main_listener.arn)
pulumi.export("main_alb_obs_listener_arn", obs_listener.arn)
pulumi.export("main_alb_dns_name", main_alb.dns_name)
pulumi.export("staging_domain", staging_domain)
if enable_observability:
    pulumi.export("openobserve_endpoint", main_alb.dns_name.apply(lambda dns: f"{dns}:5080"))
pulumi.export("sns_platform_events_topic_arn", platform_events_topic.arn)
pulumi.export("zitadel_ecr_repo_url", zitadel_ecr_repo.repository_url)
pulumi.export("ecr_repository_url", app_ecr_repo.repository_url)
pulumi.export("debezium_ecr_repo_url", debezium_ecr_repo.repository_url)
pulumi.export("app_defaults_secret_arn", app_defaults_secret.arn)
