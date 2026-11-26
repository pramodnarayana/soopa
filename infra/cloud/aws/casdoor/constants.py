"""Constants for the AWS Casdoor Identity Provider ECS Fargate stack."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _get_casdoor_image() -> str:
    version = (os.environ.get("CASDOOR_VERSION") or "").strip()
    if not version:
        raise RuntimeError(
            "Required environment variable 'CASDOOR_VERSION' is unset or empty. "
            "Ensure 'versions.env' is sourced before running Pulumi."
        )
    return f"casbin/casdoor:{version}"


@dataclass(frozen=True)
class CasdoorConstants:
    IMAGE: str = _get_casdoor_image()
    CONTAINER_NAME: str = "casdoor"
    PORT: int = 8080
    CPU: str = "256"
    MEMORY: str = "512"
    HEALTH_CHECK_PATH: str = "/api/health"
    DB_NAME: str = "casdoor"


@dataclass(frozen=True)
class EcsConstants:
    CAPACITY_PROVIDER: str = "FARGATE"
    LOG_DRIVER: str = "awslogs"
