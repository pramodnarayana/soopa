from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseConstants:
    ENGINE: str = "postgres"
    ENGINE_VERSION: str = "15.5"
    GLOBAL_DB_NAME: str = "global"
    MASTER_USERNAME: str = "postgres"
    DEFAULT_INSTANCE_CLASS: str = "db.t4g.micro"
    DEFAULT_ALLOCATED_STORAGE_GB: int = 20


@dataclass(frozen=True)
class ZitadelConstants:
    IMAGE: str = "ghcr.io/zitadel/zitadel:v3.66.0"
    CONTAINER_NAME: str = "zitadel"
    PORT: int = 8080
    CPU: str = "1024"
    MEMORY: str = "2048"


@dataclass(frozen=True)
class EcsConstants:
    CAPACITY_PROVIDER: str = "FARGATE"
    LOG_DRIVER: str = "awslogs"


@dataclass(frozen=True)
class OpenObserveConstants:
    DEFAULT_ADMIN_EMAIL: str = "admin@example.com"
