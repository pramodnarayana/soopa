from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseConstants:
    ENGINE: str = "postgres"
    ENGINE_VERSION: str = "15.19"
    GLOBAL_DB_NAME: str = "global_db"
    ZITADEL_DB_NAME: str = "zitadel_db"
    MASTER_USERNAME: str = "postgres"
    DEFAULT_NON_PROD_INSTANCE_CLASS: str = "db.t4g.micro"
    DEFAULT_PROD_INSTANCE_CLASS: str = "db.t4g.medium"
    DEFAULT_INSTANCE_CLASS: str = "db.t4g.micro"
    DEFAULT_ALLOCATED_STORAGE_GB: int = 20
    MAX_SLOT_WAL_KEEP_SIZE_MB: str = "5120"


@dataclass(frozen=True)
class ObservabilityDefaults:
    DEFAULT_PROD_LOG_RETENTION_DAYS: int = 30
    DEFAULT_NON_PROD_LOG_RETENTION_DAYS: int = 3
    DEFAULT_PROD_ECR_RETENTION_COUNT: int = 30
    DEFAULT_NON_PROD_ECR_RETENTION_COUNT: int = 10
    DEFAULT_PROD_S3_NONCURRENT_RETENTION_DAYS: int = 30
    DEFAULT_NON_PROD_S3_NONCURRENT_RETENTION_DAYS: int = 7
