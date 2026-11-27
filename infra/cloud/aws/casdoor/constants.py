"""Constants and runtime version resolution for the AWS Casdoor Identity Provider stack."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


def resolve_casdoor_version(env: Mapping[str, str] | None = None) -> str:
    """Resolve required ``CASDOOR_VERSION`` at runtime rather than module import time."""
    source = os.environ if env is None else env
    version = (source.get("CASDOOR_VERSION") or "").strip()
    if not version:
        raise RuntimeError(
            "Required environment variable 'CASDOOR_VERSION' is unset or empty. "
            "Ensure 'versions.env' is sourced before running Pulumi."
        )
    return version


@dataclass(frozen=True)
class CasdoorConstants:
    DB_INIT_IMAGE: str = "public.ecr.aws/docker/library/postgres:15.10-alpine"
    CONTAINER_NAME: str = "casdoor"
    DB_INIT_CONTAINER_NAME: str = "casdoor-db-init"
    PORT: int = 8080
    DEFAULT_CPU: str = "256"
    DEFAULT_MEMORY: str = "512"
    DEFAULT_DESIRED_COUNT: int = 1
    DEFAULT_SECRET_RECOVERY_WINDOW_DAYS: int = 30
    HEALTH_CHECK_PATH: str = "/api/health"
    HEALTH_CHECK_GRACE_PERIOD_SECONDS: int = 60
    DB_NAME: str = "casdoor"
    DB_USER: str = "casdoor_app"
    DEFAULT_DB_PORT: str = "5432"
    PLATFORM_REALM: str = "soopa-platform"
    GLOBAL_REALM: str = "soopa-global"


@dataclass(frozen=True)
class EcsConstants:
    CAPACITY_PROVIDER: str = "FARGATE"
    LOG_DRIVER: str = "awslogs"
