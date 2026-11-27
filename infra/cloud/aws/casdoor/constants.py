"""Constants and runtime version resolution for the AWS Casdoor Identity Provider stack."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class CasdoorRealm(StrEnum):
    """Canonical Casdoor Organizations (Realms) for the 3-Realm Hybrid Architecture."""

    BUILT_IN = "built-in"
    PLATFORM = "soopa-platform"
    GLOBAL = "soopa-global"


class CasdoorApplicationName(StrEnum):
    """Canonical Casdoor Application identifiers managed by cloud bootstrap."""

    BUILT_IN = "app-built-in"
    DASHBOARD = "soopa-dashboard"
    PLATFORM_ADMIN = "soopa-platform-admin"
    API_M2M = "soopa-api-m2m"


class CasdoorTokenFormat(StrEnum):
    """Casdoor Application token format values."""

    JWT_CUSTOM = "JWT-Custom"


class CasdoorGrantType(StrEnum):
    """OAuth 2.1 grant types allowed on Casdoor applications."""

    AUTHORIZATION_CODE = "authorization_code"
    REFRESH_TOKEN = "refresh_token"  # noqa: S105 - OAuth2 grant type identifier, not a credential
    CLIENT_CREDENTIALS = "client_credentials"


class CasdoorBootstrapEndpoint(StrEnum):
    """Casdoor HTTP Management API endpoints used during idempotent cloud bootstrap."""

    HEALTH = "/api/health"
    LOGIN = "/api/login"
    SET_PASSWORD = "/api/set-password"  # noqa: S105 - Casdoor API endpoint path, not a credential
    GET_ORGANIZATION = "/api/get-organization"
    ADD_ORGANIZATION = "/api/add-organization"
    UPDATE_ORGANIZATION = "/api/update-organization"
    GET_APPLICATION = "/api/get-application"
    ADD_APPLICATION = "/api/add-application"
    UPDATE_APPLICATION = "/api/update-application"
    GET_USER = "/api/get-user"
    ADD_USER = "/api/add-user"


class CasdoorAdminOAuthSecretKey(StrEnum):
    """JSON keys written to the Casdoor admin OAuth Secrets Manager payload."""

    PLATFORM_ADMIN_ID = "platform_admin_id"
    DASHBOARD_CLIENT_ID = "dashboard_client_id"
    PLATFORM_ADMIN_CLIENT_ID = "platform_admin_client_id"
    ADMIN_CLIENT_ID = "admin_client_id"
    ADMIN_CLIENT_SECRET = "admin_client_secret"  # noqa: S105 - JSON key name in Secrets Manager, not a credential
    IDENTITY_AUDIENCE = "identity_audience"


class CasdoorStackOutputKey(StrEnum):
    """Pulumi stack export keys consumed by the cloud Casdoor bootstrapper."""

    IDENTITY_DOMAIN = "identity_domain"
    ADMIN_PASSWORD_SECRET_ARN = "admin_password_secret_arn"  # noqa: S105 - Pulumi export key name, not a credential
    PLATFORM_ADMIN_PASSWORD_SECRET_ARN = "platform_admin_password_secret_arn"  # noqa: S105 - Pulumi export key name, not a credential
    ADMIN_OAUTH_SECRET_ARN = "admin_oauth_secret_arn"  # noqa: S105 - Pulumi export key name, not a credential
    PLATFORM_REALM = "platform_realm"
    GLOBAL_REALM = "global_realm"
    STAGING_DOMAIN = "staging_domain"


class CasdoorBootstrapErrorCode(StrEnum):
    """Structured error codes returned by the cloud Casdoor bootstrapper."""

    MISSING_STACK_OUTPUT = "MISSING_STACK_OUTPUT"
    INSECURE_TRANSPORT = "INSECURE_TRANSPORT"
    HEALTH_CHECK_TIMEOUT = "HEALTH_CHECK_TIMEOUT"
    ADMIN_AUTH_FAILED = "ADMIN_AUTH_FAILED"
    PASSWORD_ROTATION_FAILED = "PASSWORD_ROTATION_FAILED"  # noqa: S105 - Error code identifier, not a credential
    CASDOOR_API_ERROR = "CASDOOR_API_ERROR"
    MASKED_CLIENT_SECRET = "MASKED_CLIENT_SECRET"  # noqa: S105 - Error code identifier, not a credential
    SECRET_READ_FAILED = "SECRET_READ_FAILED"  # noqa: S105 - Error code identifier, not a credential
    SECRET_WRITE_FAILED = "SECRET_WRITE_FAILED"  # noqa: S105 - Error code identifier, not a credential


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
    PORT: int = 8000
    DEFAULT_CPU: str = "256"
    DEFAULT_MEMORY: str = "512"
    DEFAULT_DESIRED_COUNT: int = 1
    DEFAULT_SECRET_RECOVERY_WINDOW_DAYS: int = 30
    HEALTH_CHECK_PATH: str = CasdoorBootstrapEndpoint.HEALTH.value
    HEALTH_CHECK_GRACE_PERIOD_SECONDS: int = 60
    DB_NAME: str = "casdoor"
    DB_USER: str = "casdoor_app"
    DEFAULT_DB_PORT: str = "5432"
    PLATFORM_REALM: str = CasdoorRealm.PLATFORM.value
    GLOBAL_REALM: str = CasdoorRealm.GLOBAL.value
    BUILT_IN_ADMIN_USER: str = "admin"
    FACTORY_DEFAULT_ADMIN_PASSWORD: str = "123"  # noqa: S105 - Casdoor upstream factory default password used solely for initial first-boot rotation
    MASKED_SECRET_SENTINEL: str = "***"  # noqa: S105 - Casdoor API sentinel indicating a masked secret value
    MINIMAL_TOKEN_FIELDS: tuple[str, ...] = (
        "Owner",
        "Name",
        "Email",
        "EmailVerified",
        "DisplayName",
    )
    DEFAULT_AVATAR_URL: str = "https://cdn.casbin.org/img/casbin.svg"
    DEFAULT_CERT_NAME: str = "cert-built-in"
    DEFAULT_COMPANY_DOMAIN: str = "flowwolf.io"
    DEFAULT_AWS_REGION: str = "us-east-1"
    PASSWORD_TYPE: str = "bcrypt"  # noqa: S105 - Hash algorithm identifier, not a credential
    DEFAULT_USER_TYPE: str = "normal-user"
    DEFAULT_LANGUAGE: str = "en"
    PLATFORM_ADMIN_USERNAME: str = "platform_admin"
    PLATFORM_ADMIN_DISPLAY_NAME: str = "Platform Admin"
    BOOTSTRAP_HEALTH_TIMEOUT_SECONDS: int = 120
    BOOTSTRAP_HEALTH_POLL_INTERVAL_SECONDS: float = 2.0
    BOOTSTRAP_HTTP_TIMEOUT_SECONDS: float = 15.0
    TOKEN_EXPIRE_HOURS: int = 1
    REFRESH_TOKEN_EXPIRE_HOURS: int = 24


@dataclass(frozen=True)
class EcsConstants:
    CAPACITY_PROVIDER: str = "FARGATE"
    LOG_DRIVER: str = "awslogs"
