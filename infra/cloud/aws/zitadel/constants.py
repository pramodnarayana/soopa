import os
from dataclasses import dataclass


def _get_identity_image() -> str:
    version = (os.environ.get("IDENTITY_VERSION") or "").strip()
    if not version:
        raise RuntimeError(
            "Required environment variable 'IDENTITY_VERSION' is unset or empty. "
            "Ensure 'versions.env' is sourced before running Pulumi."
        )
    return f"ghcr.io/zitadel/zitadel:{version}"


@dataclass(frozen=True)
class ZitadelConstants:
    IMAGE: str = _get_identity_image()
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
