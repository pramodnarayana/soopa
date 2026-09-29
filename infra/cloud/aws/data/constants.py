from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseConstants:
    ENGINE: str = "postgres"
    ENGINE_VERSION: str = "15.19"
    GLOBAL_DB_NAME: str = "global_db"
    MASTER_USERNAME: str = "postgres"
    DEFAULT_INSTANCE_CLASS: str = "db.t4g.micro"
    DEFAULT_ALLOCATED_STORAGE_GB: int = 20
