import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ZitadelConstants:
    IMAGE: str = f"ghcr.io/zitadel/zitadel:{os.environ['IDENTITY_VERSION']}"
    CONTAINER_NAME: str = "zitadel"
    PORT: int = 8080
    CPU: str = "1024"
    MEMORY: str = "2048"


@dataclass(frozen=True)
class EcsConstants:
    CAPACITY_PROVIDER: str = "FARGATE"
    LOG_DRIVER: str = "awslogs"
