"""
Dashboard Frontend Stack
========================
Provisions S3 + CloudFront for the SPA dashboard.
"""

import json

import pulumi
import pulumi_aws as aws

_env = pulumi.get_stack()
_prefix = f"{_env}-"
_TAGS = {"ManagedBy": "pulumi", "Component": "dashboard", "Environment": _env}

config = pulumi.Config()
platform_stack_ref = config.get("platform_stack") or f"organization/platform/{_env}"
platform = pulumi.StackReference(platform_stack_ref)

staging_domain = platform.require_output("staging_domain")
dashboard_domain = staging_domain.apply(lambda d: f"dashboard.{d}")

# Extract root domain (e.g., flowwolf.io from staging.flowwolf.io)
root_domain = staging_domain.apply(lambda d: ".".join(d.split(".")[-2:]))

# Get ACM Certificate (must be us-east-1 for CloudFront)
cert = aws.acm.get_certificate_output(domain=root_domain, most_recent=True, statuses=["ISSUED"])

# 1. Create S3 Bucket for static files
bucket = aws.s3.BucketV2(
    f"{_prefix}dashboard-assets",
    bucket=pulumi.Output.concat(_prefix, "dashboard-assets-", pulumi.get_project()),
    tags=_TAGS,
)

# Block all public access (CloudFront will access it via OAC)
public_access_block = aws.s3.BucketPublicAccessBlock(
    f"{_prefix}dashboard-assets-pab",
    bucket=bucket.id,
    block_public_acls=True,
    block_public_policy=True,
    ignore_public_acls=True,
    restrict_public_buckets=True,
)

# 2. Create Origin Access Control
oac = aws.cloudfront.OriginAccessControl(
    f"{_prefix}dashboard-oac",
    name=f"{_prefix}dashboard-oac",
    description="OAC for dashboard S3 bucket",
    origin_access_control_origin_type="s3",
    signing_behavior="always",
    signing_protocol="sigv4",
)

# 3. Create CloudFront Distribution
distribution = aws.cloudfront.Distribution(
    f"{_prefix}dashboard-cdn",
    enabled=True,
    is_ipv6_enabled=True,
    default_root_object="index.html",
    aliases=[dashboard_domain],
    origins=[
        aws.cloudfront.DistributionOriginArgs(
            domain_name=bucket.bucket_regional_domain_name,
            origin_id=bucket.id,
            origin_access_control_id=oac.id,
        )
    ],
    default_cache_behavior=aws.cloudfront.DistributionDefaultCacheBehaviorArgs(
        allowed_methods=["GET", "HEAD", "OPTIONS"],
        cached_methods=["GET", "HEAD"],
        target_origin_id=bucket.id,
        forwarded_values=aws.cloudfront.DistributionDefaultCacheBehaviorForwardedValuesArgs(
            query_string=False,
            cookies=aws.cloudfront.DistributionDefaultCacheBehaviorForwardedValuesCookiesArgs(
                forward="none",
            ),
        ),
        viewer_protocol_policy="redirect-to-https",
        min_ttl=0,
        default_ttl=3600,
        max_ttl=86400,
    ),
    # SPA Routing: Redirect 404 to index.html
    custom_error_responses=[
        aws.cloudfront.DistributionCustomErrorResponseArgs(
            error_code=404,
            response_code=200,
            response_page_path="/index.html",
            error_caching_min_ttl=10,
        ),
        aws.cloudfront.DistributionCustomErrorResponseArgs(
            error_code=403,
            response_code=200,
            response_page_path="/index.html",
            error_caching_min_ttl=10,
        ),
    ],
    price_class="PriceClass_100",
    restrictions=aws.cloudfront.DistributionRestrictionsArgs(
        geo_restriction=aws.cloudfront.DistributionRestrictionsGeoRestrictionArgs(
            restriction_type="none",
        ),
    ),
    viewer_certificate=aws.cloudfront.DistributionViewerCertificateArgs(
        acm_certificate_arn=cert.arn,
        ssl_support_method="sni-only",
        minimum_protocol_version="TLSv1.2_2021",
    ),
    tags=_TAGS,
)

# 4. S3 Bucket Policy to allow CloudFront OAC
bucket_policy = aws.s3.BucketPolicy(
    f"{_prefix}dashboard-bucket-policy",
    bucket=bucket.id,
    policy=pulumi.Output.all(bucket.arn, distribution.arn).apply(
        lambda args: json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "cloudfront.amazonaws.com"},
                        "Action": "s3:GetObject",
                        "Resource": f"{args[0]}/*",
                        "Condition": {"StringEquals": {"AWS:SourceArn": args[1]}},
                    }
                ],
            }
        )
    ),
    opts=pulumi.ResourceOptions(depends_on=[public_access_block]),
)

# 5. Route53 DNS Record for Dashboard
hosted_zone = aws.route53.get_zone_output(name=staging_domain)

dns_record = aws.route53.Record(
    f"{_prefix}dashboard-dns",
    zone_id=hosted_zone.id,
    name=dashboard_domain,
    type="A",
    aliases=[
        aws.route53.RecordAliasArgs(
            name=distribution.domain_name,
            zone_id=distribution.hosted_zone_id,
            evaluate_target_health=False,
        )
    ],
)

# ── Exports ───────────────────────────────────────────────────────────────────
pulumi.export("dashboard_s3_bucket", bucket.id)
pulumi.export("dashboard_cloudfront_id", distribution.id)
pulumi.export("dashboard_cloudfront_domain", distribution.domain_name)
pulumi.export("dashboard_url", dashboard_domain.apply(lambda d: f"https://{d}"))
