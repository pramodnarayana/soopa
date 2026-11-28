"""
Edge/Routing Stack
==================
Centralized DNS routing and Edge policies for all subdomains.
"""

import pulumi
import pulumi_aws as aws
from infra_seedwork.network import provision_route53_alias_record

_env = pulumi.get_stack()
_prefix = f"{_env}-"
_TAGS = {"ManagedBy": "pulumi", "Component": "routing", "Environment": _env}

config = pulumi.Config()
platform_stack_ref = config.get("platform_stack") or f"organization/platform/{_env}"
dashboard_stack_ref = config.get("dashboard_stack") or f"organization/dashboard/{_env}"

platform = pulumi.StackReference(platform_stack_ref)
dashboard = pulumi.StackReference(dashboard_stack_ref)

staging_domain = platform.require_output("staging_domain")
main_alb_dns_name = platform.require_output("main_alb_dns_name")
main_alb_zone_id = platform.require_output("main_alb_zone_id")

dashboard_cloudfront_domain = dashboard.require_output("dashboard_cloudfront_domain")
dashboard_cloudfront_zone_id = dashboard.require_output("dashboard_cloudfront_zone_id")

hosted_zone = aws.route53.get_zone_output(name=staging_domain)

# ── 1. API Subdomain ──────────────────────────────────────────────────────────
api_dns_record = provision_route53_alias_record(
    name=f"{_prefix}api-dns",
    zone_id=hosted_zone.id,
    record_name=pulumi.Output.concat("api.", staging_domain),
    alias_target_dns_name=main_alb_dns_name,
    alias_target_zone_id=main_alb_zone_id,
)

# ── 2. Per-Tenant AS2 Wildcard Subdomain (*.as2.<domain>) ─────────────────────
as2_wildcard_dns_record = provision_route53_alias_record(
    name=f"{_prefix}as2-wildcard-dns",
    zone_id=hosted_zone.id,
    record_name=pulumi.Output.concat("*.as2.", staging_domain),
    alias_target_dns_name=main_alb_dns_name,
    alias_target_zone_id=main_alb_zone_id,
)

# ── 3. OpenAS2 Subdomain ──────────────────────────────────────────────────────
openas2_dns_record = provision_route53_alias_record(
    name=f"{_prefix}openas2-dns",
    zone_id=hosted_zone.id,
    record_name=pulumi.Output.concat("openas2.", staging_domain),
    alias_target_dns_name=main_alb_dns_name,
    alias_target_zone_id=main_alb_zone_id,
)

# ── 4. Dashboard Subdomain ────────────────────────────────────────────────────
dashboard_dns_record = provision_route53_alias_record(
    name=f"{_prefix}dashboard-dns",
    zone_id=hosted_zone.id,
    record_name=pulumi.Output.concat("dashboard.", staging_domain),
    alias_target_dns_name=dashboard_cloudfront_domain,
    alias_target_zone_id=dashboard_cloudfront_zone_id,
)

pulumi.export("api_domain", api_dns_record.name)
pulumi.export("as2_wildcard_domain", as2_wildcard_dns_record.name)
pulumi.export("openas2_domain", openas2_dns_record.name)
pulumi.export("dashboard_domain", dashboard_dns_record.name)
