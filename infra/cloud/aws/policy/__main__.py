from pulumi_policy import (
    EnforcementLevel,
    PolicyPack,
    ReportViolation,
    ResourceValidationArgs,
    ResourceValidationPolicy,
)


def check_s3_bucket_acl(args: ResourceValidationArgs, report_violation: ReportViolation) -> None:
    """Ensure S3 buckets do not have public read/write access."""
    if args.resource_type == "aws:s3/bucket:Bucket":
        acl = args.props.get("acl")
        if acl in ["public-read", "public-read-write"]:
            report_violation(f"S3 Buckets must not have public ACL '{acl}'.")


def check_rds_encryption(args: ResourceValidationArgs, report_violation: ReportViolation) -> None:
    """Ensure RDS instances are encrypted at rest."""
    if args.resource_type == "aws:rds/instance:Instance":
        storage_encrypted = args.props.get("storageEncrypted", False)
        if not storage_encrypted:
            report_violation("RDS Instances must have storageEncrypted=True.")


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
                if from_port in [22, 5432] or to_port in [22, 5432]:
                    report_violation(
                        "Security Groups must not allow 0.0.0.0/0 ingress on ports 22 or 5432."
                    )


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
            name="sg-no-open-ingress",
            description="Prohibits open 0.0.0.0/0 ingress on sensitive ports.",
            validate=check_sg_ingress,
        ),
    ],
)
