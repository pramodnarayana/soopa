"""
Edge/Routing Stack
==================
Centralized DNS routing and Edge policies for all subdomains.
"""

import pulumi
import pulumi_aws as aws

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
api_dns_record = aws.route53.Record(
    f"{_prefix}api-dns",
    zone_id=hosted_zone.id,
    name=pulumi.Output.concat("api.", staging_domain),
    type="A",
    aliases=[
        aws.route53.RecordAliasArgs(
            name=main_alb_dns_name,
            zone_id=main_alb_zone_id,
            evaluate_target_health=False,
        )
    ],
)

# ── 2. EDI Subdomain ──────────────────────────────────────────────────────────
edi_dns_record = aws.route53.Record(
    f"{_prefix}edi-dns",
    zone_id=hosted_zone.id,
    name=pulumi.Output.concat("edi.", staging_domain),
    type="A",
    aliases=[
        aws.route53.RecordAliasArgs(
            name=main_alb_dns_name,
            zone_id=main_alb_zone_id,
            evaluate_target_health=False,
        )
    ],
)

# ── 3. OpenAS2 Subdomain ──────────────────────────────────────────────────────────
openas2_dns_record = aws.route53.Record(
    f"{_prefix}openas2-dns",
    zone_id=hosted_zone.id,
    name=pulumi.Output.concat("openas2.", staging_domain),
    type="A",
    aliases=[
        aws.route53.RecordAliasArgs(
            name=main_alb_dns_name,
            zone_id=main_alb_zone_id,
            evaluate_target_health=False,
        )
    ],
)

# ── 4. Dashboard Subdomain ────────────────────────────────────────────────────
dashboard_dns_record = aws.route53.Record(
    f"{_prefix}dashboard-dns",
    zone_id=hosted_zone.id,
    name=pulumi.Output.concat("dashboard.", staging_domain),
    type="A",
    aliases=[
        aws.route53.RecordAliasArgs(
            name=dashboard_cloudfront_domain,
            zone_id=dashboard_cloudfront_zone_id,
            evaluate_target_health=False,
        )
    ],
)

pulumi.export("api_domain", api_dns_record.name)
pulumi.export("edi_domain", edi_dns_record.name)
pulumi.export("openas2_domain", openas2_dns_record.name)
pulumi.export("dashboard_domain", dashboard_dns_record.name)
