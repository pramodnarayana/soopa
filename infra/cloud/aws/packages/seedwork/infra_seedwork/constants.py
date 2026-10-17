from dataclasses import dataclass
from enum import IntEnum


@dataclass(frozen=True)
class DatabaseConstants:
    ENGINE: str = "postgres"
    ENGINE_VERSION: str = "15.19"
    GLOBAL_DB_NAME: str = "global_db"
    ZITADEL_DB_NAME: str = "zitadel_db"
    MASTER_USERNAME: str = "postgres"
    DEFAULT_INSTANCE_CLASS: str = "db.t4g.micro"
    DEFAULT_ALLOCATED_STORAGE_GB: int = 20
    MAX_SLOT_WAL_KEEP_SIZE_MB: str = "5120"


class LogRetentionPolicy(IntEnum):
    """
    Enterprise Data Governance Log Retention Policies.

    Defines approved SLA durations that balance FinOps cost control
    with statutory compliance requirements. All tiers are guaranteed to be
    accepted across CloudWatch, S3 Lifecycles, and OpenObserve compactor.
    """

    EPHEMERAL = 1  # 24h debug / load-test runs
    NON_PROD = 3  # Staging / development standard
    WEEKLY = 7  # Sprint-length integration runs
    BIWEEKLY = 14  # 2-week testing cycles
    STANDARD = 30  # Standard production baseline (SOC2)
    COMPLIANCE = 90  # Quarterly audit retention (PCI-DSS)
    ANNUAL = 365  # Statutory 1-year compliance


@dataclass(frozen=True)
class ObservabilityDefaults:
    DEFAULT_LOG_RETENTION_DAYS: int = LogRetentionPolicy.STANDARD.value
    DEFAULT_ECR_MAX_IMAGE_COUNT: int = 10
    DEFAULT_S3_NONCURRENT_RETENTION_DAYS: int = 30


def validate_log_retention(days: int) -> int:
    """
    Enforces enterprise retention policy governance.

    Rejects unapproved retention durations, ensuring all environments conform to
    audited compliance tiers and cloud provider retention boundaries.
    """
    allowed_values = {tier.value for tier in LogRetentionPolicy}
    if days not in allowed_values:
        policies = ", ".join(f"{t.name}={t.value}d" for t in LogRetentionPolicy)
        raise ValueError(
            f"Retention duration '{days}' days is not an approved enterprise policy tier. "
            f"Approved policies: {policies}"
        )
    return days
