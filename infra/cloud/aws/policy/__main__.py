import json

from pulumi_policy import (
    EnforcementLevel,
    PolicyPack,
    ReportViolation,
    ResourceValidationArgs,
    ResourceValidationPolicy,
)


def check_s3_bucket_acl(args: ResourceValidationArgs, report_violation: ReportViolation) -> None:
    """Ensure S3 buckets do not have public read/write access."""
    if args.resource_type == "aws:s3/bucketAclV2:BucketAclV2":
        acl = args.props.get("acl")
        if acl in ["public-read", "public-read-write"]:
            report_violation(f"S3 Buckets must not have public ACL '{acl}'.")

    if args.resource_type == "aws:s3/bucketPolicy:BucketPolicy":
        policy = args.props.get("policy")
        if policy and isinstance(policy, str):
            try:
                policy_doc = json.loads(policy)
                for statement in policy_doc.get("Statement", []):
                    if statement.get("Effect") == "Allow" and statement.get("Principal") == "*":
                        report_violation("S3 Bucket policies must not allow public access.")
            except json.JSONDecodeError as e:
                report_violation(f"S3 Bucket policy is invalid JSON: {e}")


def check_rds_encryption(args: ResourceValidationArgs, report_violation: ReportViolation) -> None:
    """Ensure RDS instances are encrypted at rest."""
    if args.resource_type == "aws:rds/instance:Instance":
        storage_encrypted = args.props.get("storageEncrypted", False)
        if not storage_encrypted:
            report_violation("RDS Instances must have storageEncrypted=True.")


def check_rds_deletion_protection(
    args: ResourceValidationArgs, report_violation: ReportViolation
) -> None:
    """Ensure RDS instances have deletion protection enabled."""
    if args.resource_type == "aws:rds/instance:Instance":
        deletion_protection = args.props.get("deletionProtection", False)
        if not deletion_protection:
            report_violation("RDS Instances must have deletionProtection=True.")


def check_sg_ingress(args: ResourceValidationArgs, report_violation: ReportViolation) -> None:
    """Ensure Security Groups do not allow unrestricted SSH or Postgres access."""
    if args.resource_type == "aws:ec2/securityGroup:SecurityGroup":
        ingress_rules = args.props.get("ingress", [])
        for rule in ingress_rules:
            if not isinstance(rule, dict):
                continue
            cidr_blocks = rule.get("cidrBlocks", [])
            if "0.0.0.0/0" in cidr_blocks:
                from_port = rule.get("fromPort")
                to_port = rule.get("toPort")

                # Check if sensitive ports (22, 5432) fall within the allowed range
                sensitive_ports = [22, 5432]
                for port in sensitive_ports:
                    if (
                        from_port is not None
                        and to_port is not None
                        and from_port <= port <= to_port
                    ):
                        report_violation(
                            f"Security Groups must not allow 0.0.0.0/0 ingress on port {port}."
                        )
                        break


PolicyPack(
    name="platform-policies",
    enforcement_level=EnforcementLevel.MANDATORY,
    policies=[
        ResourceValidationPolicy(
            name="s3-no-public-read",
            description="Prohibits public read/write access on S3 buckets.",
            validate=check_s3_bucket_acl,
        ),
        ResourceValidationPolicy(
            name="rds-storage-encrypted",
            description="Requires storage encryption on RDS instances.",
            validate=check_rds_encryption,
        ),
        ResourceValidationPolicy(
            name="rds-deletion-protection",
            description="Requires deletion protection on RDS instances.",
            validate=check_rds_deletion_protection,
        ),
        ResourceValidationPolicy(
            name="sg-no-open-ingress",
            description="Prohibits open 0.0.0.0/0 ingress on sensitive ports.",
            validate=check_sg_ingress,
        ),
    ],
)
