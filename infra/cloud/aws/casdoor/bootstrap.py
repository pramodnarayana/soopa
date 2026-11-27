"""Idempotent Cloud Bootstrapper for the AWS Casdoor Identity Provider.

Executed after `infra/cloud/aws/casdoor` deploys in CI/CD (and safely re-runnable
by operators) to:
1. Wait for Casdoor `/api/health` readiness.
2. Authenticate as `built-in/admin` and rotate the factory default password (`123`)
   to the Secrets Manager-managed `admin_password_secret` on first boot.
3. Idempotently ensure canonical organizations (`soopa-platform`, `soopa-global`),
   OAuth 2.1 applications (`soopa-dashboard`, `soopa-platform-admin`, `soopa-api-m2m`)
   with compact `JWT-Custom` tokens, and the initial `platform_admin` operator user.
4. Populate `admin_oauth_secret_arn` in AWS Secrets Manager with the canonical JSON
   payload consumed by `platform/migrator`, `apps/api`, `apps/ucp/workers`, and
   `apps/dashboard`.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Protocol, TypeVar

import boto3
import botocore.exceptions
import httpx
import structlog
from constants import (
    CasdoorAdminOAuthSecretKey,
    CasdoorApplicationName,
    CasdoorBootstrapEndpoint,
    CasdoorBootstrapErrorCode,
    CasdoorConstants,
    CasdoorGrantType,
    CasdoorRealm,
    CasdoorStackOutputKey,
    CasdoorTokenFormat,
)
from infra_seedwork.tasks.run_ecs_task import StackOutputReaderPort, read_pulumi_stack_outputs

logger = structlog.get_logger(__name__)

T = TypeVar("T")

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CASDOOR_STACK_DIR = _REPO_ROOT / "infra" / "cloud" / "aws" / "casdoor"
_PLATFORM_STACK_DIR = _REPO_ROOT / "infra" / "cloud" / "aws" / "platform"
_CASDOOR_ADMIN_OWNER = "admin"
_CASDOOR_STATUS_OK = "ok"
_CASDOOR_STATUS_ERROR = "error"
_SECRETS_NOT_FOUND_ERROR_CODE = "ResourceNotFoundException"


# ── First-Class Result & Error DTOs ───────────────────────────────────────────


@dataclass(frozen=True)
class CasdoorBootstrapError:
    """Structured operational error returned by the Casdoor cloud bootstrapper."""

    code: CasdoorBootstrapErrorCode
    detail: str
    endpoint: str = ""


@dataclass(frozen=True)
class BootstrapResult(Generic[T]):
    """First-class Result container avoiding exceptions for expected operational failures."""

    value: T | None = None
    error: CasdoorBootstrapError | None = None

    @property
    def is_ok(self) -> bool:
        return self.error is None

    @classmethod
    def ok(cls, value: T) -> BootstrapResult[T]:
        return cls(value=value, error=None)

    @classmethod
    def fail(
        cls,
        code: CasdoorBootstrapErrorCode,
        detail: str,
        *,
        endpoint: str = "",
    ) -> BootstrapResult[T]:
        return cls(
            value=None,
            error=CasdoorBootstrapError(code=code, detail=detail, endpoint=endpoint),
        )


@dataclass(frozen=True)
class CasdoorBootstrapConfig:
    """Immutable boundary configuration for bootstrapping a cloud Casdoor environment."""

    identity_base_url: str
    dashboard_base_url: str
    platform_realm: str
    global_realm: str
    admin_password_secret_arn: str
    platform_admin_password_secret_arn: str
    admin_oauth_secret_arn: str
    platform_admin_email: str
    health_timeout_seconds: int = CasdoorConstants.BOOTSTRAP_HEALTH_TIMEOUT_SECONDS
    health_poll_interval_seconds: float = CasdoorConstants.BOOTSTRAP_HEALTH_POLL_INTERVAL_SECONDS


@dataclass(frozen=True)
class CasdoorApplicationSpec:
    """Desired configuration for a Casdoor OAuth 2.1 application."""

    name: CasdoorApplicationName
    display_name: str
    organization: str
    redirect_uris: tuple[str, ...]
    is_shared: bool
    grant_types: tuple[CasdoorGrantType, ...]
    enable_sign_up: bool
    enable_password: bool
    enable_webauthn: bool


@dataclass(frozen=True)
class CasdoorClientCredentials:
    """Resolved Casdoor OAuth application credentials."""

    client_id: str
    client_secret: str


@dataclass(frozen=True)
class _ProvisionedApplications:
    """Bundle of canonical Casdoor OAuth application credentials provisioned in cloud."""

    dashboard: CasdoorClientCredentials
    platform_admin: CasdoorClientCredentials
    api_m2m: CasdoorClientCredentials


@dataclass(frozen=True)
class _BootstrapSecrets:
    """Pre-fetched, isolated Secrets Manager credentials required for cloud bootstrap."""

    admin_password: str
    platform_admin_password: str
    existing_oauth_payload: dict[str, str] | None


@dataclass(frozen=True)
class CasdoorBootstrapSummary:
    """Non-sensitive audit summary returned after successful cloud bootstrap."""

    identity_base_url: str
    admin_password_rotated: bool
    secret_updated: bool
    platform_admin_id: str
    dashboard_client_id: str
    platform_admin_client_id: str
    admin_client_id: str


# ── Outbound Ports (Protocols) ────────────────────────────────────────────────


class HttpResponsePort(Protocol):
    """Minimal HTTP response contract decoupled from concrete HTTP libraries."""

    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    def json(self) -> object: ...


class HttpClientPort(Protocol):
    """Stateful HTTP client port preserving Casdoor admin session cookies."""

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        json: Mapping[str, object] | None = None,
        data: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> BootstrapResult[HttpResponsePort]: ...


class SecretsStorePort(Protocol):
    """Port for reading and writing secret payloads in cloud secret storage."""

    def get_secret_string(self, secret_arn: str) -> BootstrapResult[str | None]: ...

    def put_secret_string(self, secret_arn: str, secret_string: str) -> BootstrapResult[None]: ...


ClockPort = Callable[[], float]
SleeperPort = Callable[[float], None]
SecretTokenGeneratorPort = Callable[[int], str]


# ── Concrete Infrastructure Adapters ──────────────────────────────────────────


class HttpxClientAdapter:
    """httpx-backed HTTP adapter preserving session cookies across Casdoor API calls."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        json: Mapping[str, object] | None = None,
        data: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> BootstrapResult[HttpResponsePort]:
        try:
            response = self._client.request(
                method,
                url,
                params=params,
                json=json,
                data=data,
                headers=headers,
            )
            return BootstrapResult.ok(response)
        except httpx.HTTPError as exc:
            return BootstrapResult.fail(
                CasdoorBootstrapErrorCode.CASDOOR_API_ERROR,
                f"HTTP transport error calling {method} {url}: {exc}",
                endpoint=url,
            )


class BotoSecretsManagerClientPort(Protocol):
    """Minimal boto3 Secrets Manager client protocol for structural typing."""

    def get_secret_value(self, *, SecretId: str) -> Mapping[str, object]: ...

    def put_secret_value(self, *, SecretId: str, SecretString: str) -> Mapping[str, object]: ...


class AwsSecretsManagerAdapter:
    """AWS Secrets Manager adapter implementing SecretsStorePort."""

    def __init__(self, client: BotoSecretsManagerClientPort) -> None:
        self._client = client

    def get_secret_string(self, secret_arn: str) -> BootstrapResult[str | None]:
        try:
            response = self._client.get_secret_value(SecretId=secret_arn)
        except botocore.exceptions.ClientError as exc:
            error_info = exc.response.get("Error", {})
            error_code = str(error_info.get("Code", ""))
            if error_code == _SECRETS_NOT_FOUND_ERROR_CODE:
                return BootstrapResult.ok(None)
            logger.error(
                "casdoor_secret_read_failed",
                secret_arn=secret_arn,
                aws_error_code=error_code,
            )
            return BootstrapResult.fail(
                CasdoorBootstrapErrorCode.SECRET_READ_FAILED,
                f"Failed to read secret {secret_arn}: {error_code}",
            )
        except botocore.exceptions.BotoCoreError as exc:
            logger.error("casdoor_secret_read_transport_failed", secret_arn=secret_arn)
            return BootstrapResult.fail(
                CasdoorBootstrapErrorCode.SECRET_READ_FAILED,
                f"BotoCore error reading secret {secret_arn}: {exc}",
            )

        secret_string = response.get("SecretString")
        if not isinstance(secret_string, str):
            return BootstrapResult.ok(None)
        return BootstrapResult.ok(secret_string)

    def put_secret_string(self, secret_arn: str, secret_string: str) -> BootstrapResult[None]:
        try:
            self._client.put_secret_value(SecretId=secret_arn, SecretString=secret_string)
        except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError) as exc:
            logger.error("casdoor_secret_write_failed", secret_arn=secret_arn, error=str(exc))
            return BootstrapResult.fail(
                CasdoorBootstrapErrorCode.SECRET_WRITE_FAILED,
                f"Failed to write secret {secret_arn}: {exc}",
            )
        return BootstrapResult.ok(None)


# ── Config Resolution Helper ──────────────────────────────────────────────────


def resolve_bootstrap_config(
    *,
    env_name: str,
    casdoor_stack_dir: Path = _CASDOOR_STACK_DIR,
    platform_stack_dir: Path = _PLATFORM_STACK_DIR,
    stack_output_reader: StackOutputReaderPort = read_pulumi_stack_outputs,
    environ: Mapping[str, str] | None = None,
    platform_admin_email_override: str = "",
) -> BootstrapResult[CasdoorBootstrapConfig]:
    """Build CasdoorBootstrapConfig strictly from Pulumi stack outputs and environment."""
    source_env = os.environ if environ is None else environ
    try:
        casdoor_outputs = stack_output_reader(casdoor_stack_dir, env_name)
        platform_outputs = stack_output_reader(platform_stack_dir, env_name)
    except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError, OSError) as exc:
        logger.error(
            "casdoor_bootstrap_stack_output_read_failed",
            env=env_name,
            error=str(exc),
        )
        return BootstrapResult.fail(
            CasdoorBootstrapErrorCode.MISSING_STACK_OUTPUT,
            f"Failed to read Pulumi stack outputs for '{env_name}': {exc}",
        )

    required_casdoor = (
        CasdoorStackOutputKey.IDENTITY_DOMAIN.value,
        CasdoorStackOutputKey.ADMIN_PASSWORD_SECRET_ARN.value,
        CasdoorStackOutputKey.PLATFORM_ADMIN_PASSWORD_SECRET_ARN.value,
        CasdoorStackOutputKey.ADMIN_OAUTH_SECRET_ARN.value,
        CasdoorStackOutputKey.PLATFORM_REALM.value,
        CasdoorStackOutputKey.GLOBAL_REALM.value,
    )
    missing = [key for key in required_casdoor if not (casdoor_outputs.get(key) or "").strip()]
    staging_domain_key = CasdoorStackOutputKey.STAGING_DOMAIN.value
    if not (platform_outputs.get(staging_domain_key) or "").strip():
        missing.append(f"platform.{staging_domain_key}")
    if missing:
        return BootstrapResult.fail(
            CasdoorBootstrapErrorCode.MISSING_STACK_OUTPUT,
            f"Missing required Pulumi stack outputs: {', '.join(missing)}",
        )

    identity_domain = (
        casdoor_outputs[CasdoorStackOutputKey.IDENTITY_DOMAIN.value].strip().rstrip(".")
    )
    staging_domain = platform_outputs[staging_domain_key].strip().rstrip(".")

    company_domain = (
        source_env.get("COMPANY_DOMAIN") or CasdoorConstants.DEFAULT_COMPANY_DOMAIN
    ).strip()
    admin_email = (
        platform_admin_email_override.strip()
        or (source_env.get("IDENTITY_PLATFORM_ADMIN_EMAIL") or "").strip()
        or f"admin@{company_domain}"
    )

    return BootstrapResult.ok(
        CasdoorBootstrapConfig(
            identity_base_url=f"https://{identity_domain}",
            dashboard_base_url=f"https://dashboard.{staging_domain}",
            platform_realm=casdoor_outputs[CasdoorStackOutputKey.PLATFORM_REALM.value].strip(),
            global_realm=casdoor_outputs[CasdoorStackOutputKey.GLOBAL_REALM.value].strip(),
            admin_password_secret_arn=casdoor_outputs[
                CasdoorStackOutputKey.ADMIN_PASSWORD_SECRET_ARN.value
            ].strip(),
            platform_admin_password_secret_arn=casdoor_outputs[
                CasdoorStackOutputKey.PLATFORM_ADMIN_PASSWORD_SECRET_ARN.value
            ].strip(),
            admin_oauth_secret_arn=casdoor_outputs[
                CasdoorStackOutputKey.ADMIN_OAUTH_SECRET_ARN.value
            ].strip(),
            platform_admin_email=admin_email,
        )
    )


# ── Core Idempotent Bootstrapper ──────────────────────────────────────────────


class CasdoorCloudBootstrapper:
    """Pure, idempotent cloud Casdoor topology & Secrets Manager bootstrapper."""

    def __init__(
        self,
        *,
        config: CasdoorBootstrapConfig,
        http_client: HttpClientPort,
        secrets_store: SecretsStorePort,
        clock: ClockPort = time.monotonic,
        sleeper: SleeperPort = time.sleep,
        token_generator: SecretTokenGeneratorPort = secrets.token_hex,
    ) -> None:
        self._config = config
        self._base_url = config.identity_base_url.rstrip("/")
        self._dashboard_url = config.dashboard_base_url.rstrip("/")
        self._http = http_client
        self._secrets = secrets_store
        self._clock = clock
        self._sleep = sleeper
        self._token_hex = token_generator

    def run(self) -> BootstrapResult[CasdoorBootstrapSummary]:
        """Execute full idempotent cloud Casdoor bootstrap and sync Secrets Manager."""
        logger.info(
            "casdoor_cloud_bootstrap_started",
            identity_base_url=self._base_url,
            platform_realm=self._config.platform_realm,
            global_realm=self._config.global_realm,
        )

        url_res = self._validate_https_urls()
        if not url_res.is_ok:
            return BootstrapResult(error=url_res.error)

        secrets_res = self._load_bootstrap_secrets()
        if not secrets_res.is_ok or secrets_res.value is None:
            return BootstrapResult(error=secrets_res.error)
        loaded_secrets = secrets_res.value

        health_res = self._wait_for_health()
        if not health_res.is_ok:
            return BootstrapResult(error=health_res.error)

        auth_res = self._authenticate_and_harden_admin(loaded_secrets.admin_password)
        if not auth_res.is_ok or auth_res.value is None:
            return BootstrapResult(error=auth_res.error)

        realms_res = self._ensure_realms()
        if not realms_res.is_ok:
            return BootstrapResult(error=realms_res.error)

        apps_res = self._provision_applications()
        if not apps_res.is_ok or apps_res.value is None:
            return BootstrapResult(error=apps_res.error)

        platform_admin_res = self._ensure_platform_admin_user(
            loaded_secrets.platform_admin_password
        )
        if not platform_admin_res.is_ok or platform_admin_res.value is None:
            return BootstrapResult(error=platform_admin_res.error)

        sync_res = self._sync_admin_oauth_secret(
            existing_payload=loaded_secrets.existing_oauth_payload,
            apps=apps_res.value,
            platform_admin_id=platform_admin_res.value,
        )
        if not sync_res.is_ok or sync_res.value is None:
            return BootstrapResult(error=sync_res.error)

        summary = CasdoorBootstrapSummary(
            identity_base_url=self._base_url,
            admin_password_rotated=auth_res.value,
            secret_updated=sync_res.value,
            platform_admin_id=platform_admin_res.value,
            dashboard_client_id=apps_res.value.dashboard.client_id,
            platform_admin_client_id=apps_res.value.platform_admin.client_id,
            admin_client_id=apps_res.value.api_m2m.client_id,
        )
        logger.info(
            "casdoor_cloud_bootstrap_completed",
            identity_base_url=summary.identity_base_url,
            admin_password_rotated=summary.admin_password_rotated,
            secret_updated=summary.secret_updated,
            platform_admin_id=summary.platform_admin_id,
            dashboard_client_id=summary.dashboard_client_id,
            platform_admin_client_id=summary.platform_admin_client_id,
            admin_client_id=summary.admin_client_id,
        )
        return BootstrapResult.ok(summary)

    def _validate_https_urls(self) -> BootstrapResult[None]:
        for label, url in (
            ("identity_base_url", self._base_url),
            ("dashboard_base_url", self._dashboard_url),
        ):
            if not url.startswith("https://"):
                logger.error("casdoor_bootstrap_insecure_url", field=label, url=url)
                return BootstrapResult.fail(
                    CasdoorBootstrapErrorCode.INSECURE_TRANSPORT,
                    f"Cloud Casdoor bootstrap requires HTTPS for {label} (got '{url}').",
                )
        return BootstrapResult.ok(None)

    def _load_bootstrap_secrets(self) -> BootstrapResult[_BootstrapSecrets]:
        admin_pwd_res = self._read_required_secret(
            self._config.admin_password_secret_arn,
            label="admin_password_secret",
        )
        if not admin_pwd_res.is_ok or admin_pwd_res.value is None:
            return BootstrapResult(error=admin_pwd_res.error)

        platform_admin_pwd_res = self._read_required_secret(
            self._config.platform_admin_password_secret_arn,
            label="platform_admin_password_secret",
        )
        if not platform_admin_pwd_res.is_ok or platform_admin_pwd_res.value is None:
            return BootstrapResult(error=platform_admin_pwd_res.error)

        existing_oauth_res = self._read_existing_oauth_payload()
        if not existing_oauth_res.is_ok:
            return BootstrapResult(error=existing_oauth_res.error)

        return BootstrapResult.ok(
            _BootstrapSecrets(
                admin_password=admin_pwd_res.value,
                platform_admin_password=platform_admin_pwd_res.value,
                existing_oauth_payload=existing_oauth_res.value,
            )
        )

    def _ensure_realms(self) -> BootstrapResult[None]:
        platform_res = self._ensure_organization(
            name=self._config.platform_realm,
            display_name="Soopa Platform Operators",
            default_application=CasdoorApplicationName.PLATFORM_ADMIN.value,
        )
        if not platform_res.is_ok:
            return platform_res
        return self._ensure_organization(
            name=self._config.global_realm,
            display_name="Soopa Global (Individuals & Standard Companies)",
            default_application=CasdoorApplicationName.DASHBOARD.value,
        )

    def _provision_applications(self) -> BootstrapResult[_ProvisionedApplications]:
        spa_redirect_uris = (f"{self._dashboard_url}/callback", self._dashboard_url)

        dashboard_res = self._ensure_application(
            CasdoorApplicationSpec(
                name=CasdoorApplicationName.DASHBOARD,
                display_name="Soopa Unified Dashboard",
                organization=CasdoorRealm.BUILT_IN.value,
                redirect_uris=spa_redirect_uris,
                is_shared=True,
                grant_types=(
                    CasdoorGrantType.AUTHORIZATION_CODE,
                    CasdoorGrantType.REFRESH_TOKEN,
                ),
                enable_sign_up=True,
                enable_password=True,
                enable_webauthn=True,
            )
        )
        if not dashboard_res.is_ok or dashboard_res.value is None:
            return BootstrapResult(error=dashboard_res.error)

        platform_res = self._ensure_application(
            CasdoorApplicationSpec(
                name=CasdoorApplicationName.PLATFORM_ADMIN,
                display_name="Soopa Platform Operator Console",
                organization=self._config.platform_realm,
                redirect_uris=spa_redirect_uris,
                is_shared=False,
                grant_types=(
                    CasdoorGrantType.AUTHORIZATION_CODE,
                    CasdoorGrantType.REFRESH_TOKEN,
                ),
                enable_sign_up=False,
                enable_password=True,
                enable_webauthn=True,
            )
        )
        if not platform_res.is_ok or platform_res.value is None:
            return BootstrapResult(error=platform_res.error)

        m2m_res = self._ensure_application(
            CasdoorApplicationSpec(
                name=CasdoorApplicationName.API_M2M,
                display_name="Soopa Backend Admin & M2M",
                organization=CasdoorRealm.BUILT_IN.value,
                redirect_uris=(),
                is_shared=True,
                grant_types=(CasdoorGrantType.CLIENT_CREDENTIALS,),
                enable_sign_up=False,
                enable_password=False,
                enable_webauthn=False,
            )
        )
        if not m2m_res.is_ok or m2m_res.value is None:
            return BootstrapResult(error=m2m_res.error)

        m2m_secret = m2m_res.value.client_secret
        if not m2m_secret or m2m_secret == CasdoorConstants.MASKED_SECRET_SENTINEL:
            logger.error(
                "casdoor_m2m_client_secret_masked",
                application=CasdoorApplicationName.API_M2M.value,
            )
            return BootstrapResult.fail(
                CasdoorBootstrapErrorCode.MASKED_CLIENT_SECRET,
                "Casdoor returned an empty or masked clientSecret for soopa-api-m2m.",
                endpoint=CasdoorBootstrapEndpoint.GET_APPLICATION.value,
            )

        return BootstrapResult.ok(
            _ProvisionedApplications(
                dashboard=dashboard_res.value,
                platform_admin=platform_res.value,
                api_m2m=m2m_res.value,
            )
        )

    def _sync_admin_oauth_secret(
        self,
        *,
        existing_payload: Mapping[str, str] | None,
        apps: _ProvisionedApplications,
        platform_admin_id: str,
    ) -> BootstrapResult[bool]:
        target_payload: dict[str, str] = {
            CasdoorAdminOAuthSecretKey.PLATFORM_ADMIN_ID.value: platform_admin_id,
            CasdoorAdminOAuthSecretKey.DASHBOARD_CLIENT_ID.value: apps.dashboard.client_id,
            CasdoorAdminOAuthSecretKey.PLATFORM_ADMIN_CLIENT_ID.value: (
                apps.platform_admin.client_id
            ),
            CasdoorAdminOAuthSecretKey.ADMIN_CLIENT_ID.value: apps.api_m2m.client_id,
            CasdoorAdminOAuthSecretKey.ADMIN_CLIENT_SECRET.value: apps.api_m2m.client_secret,
            CasdoorAdminOAuthSecretKey.IDENTITY_AUDIENCE.value: ",".join(
                (
                    apps.dashboard.client_id,
                    apps.platform_admin.client_id,
                    apps.api_m2m.client_id,
                )
            ),
        }
        if existing_payload == target_payload:
            logger.info(
                "casdoor_admin_oauth_secret_unchanged",
                secret_arn=self._config.admin_oauth_secret_arn,
            )
            return BootstrapResult.ok(False)

        put_res = self._secrets.put_secret_string(
            self._config.admin_oauth_secret_arn,
            json.dumps(target_payload, sort_keys=True),
        )
        if not put_res.is_ok:
            return BootstrapResult(error=put_res.error)

        logger.info(
            "casdoor_admin_oauth_secret_updated",
            secret_arn=self._config.admin_oauth_secret_arn,
            dashboard_client_id=apps.dashboard.client_id,
            platform_admin_client_id=apps.platform_admin.client_id,
            admin_client_id=apps.api_m2m.client_id,
        )
        return BootstrapResult.ok(True)

    # ── Private Orchestration Helpers ─────────────────────────────────────────

    def _read_required_secret(self, secret_arn: str, *, label: str) -> BootstrapResult[str]:
        res = self._secrets.get_secret_string(secret_arn)
        if not res.is_ok:
            return BootstrapResult(error=res.error)
        if not res.value or not res.value.strip():
            logger.error("casdoor_required_secret_empty", label=label, secret_arn=secret_arn)
            return BootstrapResult.fail(
                CasdoorBootstrapErrorCode.SECRET_READ_FAILED,
                f"Casdoor required secret '{label}' is missing or empty.",
            )
        return BootstrapResult.ok(res.value)

    def _read_existing_oauth_payload(self) -> BootstrapResult[dict[str, str] | None]:
        res = self._secrets.get_secret_string(self._config.admin_oauth_secret_arn)
        if not res.is_ok:
            return BootstrapResult(error=res.error)
        if res.value is None or not res.value.strip():
            return BootstrapResult.ok(None)
        try:
            parsed = json.loads(res.value)
        except json.JSONDecodeError as exc:
            logger.error(
                "casdoor_admin_oauth_secret_corrupt_json",
                secret_arn=self._config.admin_oauth_secret_arn,
                error=str(exc),
            )
            return BootstrapResult.fail(
                CasdoorBootstrapErrorCode.SECRET_READ_FAILED,
                "Existing Casdoor admin OAuth secret contains invalid JSON.",
            )
        if not isinstance(parsed, dict):
            logger.error(
                "casdoor_admin_oauth_secret_invalid_shape",
                secret_arn=self._config.admin_oauth_secret_arn,
            )
            return BootstrapResult.fail(
                CasdoorBootstrapErrorCode.SECRET_READ_FAILED,
                "Existing Casdoor admin OAuth secret must be a JSON object.",
            )
        return BootstrapResult.ok({str(k): str(v) for k, v in parsed.items()})

    def _wait_for_health(self) -> BootstrapResult[None]:
        deadline = self._clock() + self._config.health_timeout_seconds
        health_url = f"{self._base_url}{CasdoorBootstrapEndpoint.HEALTH.value}"
        logger.info("casdoor_bootstrap_waiting_for_health", url=health_url)

        while True:
            resp_res = self._http.request("GET", health_url)
            if resp_res.is_ok and resp_res.value is not None and resp_res.value.status_code == 200:
                logger.info("casdoor_bootstrap_healthy", url=health_url)
                return BootstrapResult.ok(None)

            if self._clock() >= deadline:
                logger.error(
                    "casdoor_bootstrap_health_timeout",
                    url=health_url,
                    timeout_seconds=self._config.health_timeout_seconds,
                )
                return BootstrapResult.fail(
                    CasdoorBootstrapErrorCode.HEALTH_CHECK_TIMEOUT,
                    f"Casdoor did not become healthy at {health_url} within {self._config.health_timeout_seconds}s.",
                    endpoint=CasdoorBootstrapEndpoint.HEALTH.value,
                )

            logger.warning("casdoor_bootstrap_health_retrying", url=health_url)
            self._sleep(self._config.health_poll_interval_seconds)

    def _login_with_password(self, password: str) -> BootstrapResult[bool]:
        endpoint = CasdoorBootstrapEndpoint.LOGIN
        resp_res = self._http.request(
            "POST",
            f"{self._base_url}{endpoint.value}",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json={
                "application": CasdoorApplicationName.BUILT_IN.value,
                "organization": CasdoorRealm.BUILT_IN.value,
                "username": CasdoorConstants.BUILT_IN_ADMIN_USER,
                "password": password,
                "type": "login",
            },
        )
        if not resp_res.is_ok or resp_res.value is None:
            logger.error(
                "casdoor_api_transport_error",
                endpoint=endpoint.value,
                detail=resp_res.error.detail if resp_res.error else "Unknown transport error",
            )
            return BootstrapResult(error=resp_res.error)
        if resp_res.value.status_code != 200:
            return BootstrapResult.ok(False)
        parsed_res = self._parse_json_object(resp_res.value, endpoint)
        if not parsed_res.is_ok or parsed_res.value is None:
            return BootstrapResult(error=parsed_res.error)
        return BootstrapResult.ok(parsed_res.value.get("status") == _CASDOOR_STATUS_OK)

    def _authenticate_and_harden_admin(self, admin_password: str) -> BootstrapResult[bool]:
        """Authenticate as built-in admin, rotating factory default `123` if still active."""
        managed_login = self._login_with_password(admin_password)
        if not managed_login.is_ok:
            return BootstrapResult(error=managed_login.error)
        if managed_login.value:
            logger.info("casdoor_builtin_admin_authenticated", rotated=False)
            return BootstrapResult.ok(False)

        factory_password = CasdoorConstants.FACTORY_DEFAULT_ADMIN_PASSWORD
        if admin_password == factory_password:
            logger.error("casdoor_builtin_admin_auth_failed", reason="managed_password_rejected")
            return BootstrapResult.fail(
                CasdoorBootstrapErrorCode.ADMIN_AUTH_FAILED,
                "Failed to authenticate Casdoor built-in admin.",
                endpoint=CasdoorBootstrapEndpoint.LOGIN.value,
            )

        factory_login = self._login_with_password(factory_password)
        if not factory_login.is_ok:
            return BootstrapResult(error=factory_login.error)
        if not factory_login.value:
            logger.error(
                "casdoor_builtin_admin_auth_failed",
                reason="both_managed_and_factory_passwords_rejected",
            )
            return BootstrapResult.fail(
                CasdoorBootstrapErrorCode.ADMIN_AUTH_FAILED,
                "Failed to authenticate Casdoor built-in admin with managed or initial password.",
                endpoint=CasdoorBootstrapEndpoint.LOGIN.value,
            )

        # Casdoor v4.30+ SetPassword reads `c.Ctx.Request.Form.Get(...)` (form-encoded, NOT JSON).
        rotate_res = self._casdoor_form_request(
            "POST",
            CasdoorBootstrapEndpoint.SET_PASSWORD,
            form_data={
                "userOwner": CasdoorRealm.BUILT_IN.value,
                "userName": CasdoorConstants.BUILT_IN_ADMIN_USER,
                "oldPassword": factory_password,
                "newPassword": admin_password,
            },
        )
        if not rotate_res.is_ok:
            logger.error("casdoor_builtin_admin_password_rotation_failed")
            return BootstrapResult.fail(
                CasdoorBootstrapErrorCode.PASSWORD_ROTATION_FAILED,
                f"Failed to rotate Casdoor built-in admin password: {rotate_res.error}",
                endpoint=CasdoorBootstrapEndpoint.SET_PASSWORD.value,
            )

        # Re-authenticate immediately because Casdoor invalidates active sessions on /api/set-password.
        verify_login = self._login_with_password(admin_password)
        if not verify_login.is_ok or not verify_login.value:
            logger.error("casdoor_builtin_admin_reauth_after_rotation_failed")
            return BootstrapResult.fail(
                CasdoorBootstrapErrorCode.PASSWORD_ROTATION_FAILED,
                "Casdoor password rotation succeeded but re-authentication with new password failed.",
                endpoint=CasdoorBootstrapEndpoint.LOGIN.value,
            )

        logger.info("casdoor_builtin_admin_password_rotated")
        return BootstrapResult.ok(True)

    def _parse_json_object(
        self,
        response: HttpResponsePort,
        endpoint: CasdoorBootstrapEndpoint,
    ) -> BootstrapResult[dict[str, object]]:
        try:
            parsed = response.json()
        except ValueError as exc:
            logger.error(
                "casdoor_api_invalid_json",
                endpoint=endpoint.value,
                status_code=response.status_code,
                error=str(exc),
            )
            return BootstrapResult.fail(
                CasdoorBootstrapErrorCode.CASDOOR_API_ERROR,
                f"Non-JSON response payload on {endpoint.value}: {exc}",
                endpoint=endpoint.value,
            )
        if not isinstance(parsed, dict):
            return BootstrapResult.fail(
                CasdoorBootstrapErrorCode.CASDOOR_API_ERROR,
                f"Unexpected non-object JSON payload on {endpoint.value}",
                endpoint=endpoint.value,
            )
        return BootstrapResult.ok({str(k): v for k, v in parsed.items()})

    def _handle_casdoor_response(
        self,
        resp_res: BootstrapResult[HttpResponsePort],
        endpoint: CasdoorBootstrapEndpoint,
    ) -> BootstrapResult[dict[str, object]]:
        if not resp_res.is_ok or resp_res.value is None:
            logger.error(
                "casdoor_api_transport_error",
                endpoint=endpoint.value,
                detail=resp_res.error.detail if resp_res.error else "Unknown transport error",
            )
            return BootstrapResult(error=resp_res.error)

        response = resp_res.value
        if response.status_code >= 400:
            logger.error(
                "casdoor_api_http_error",
                endpoint=endpoint.value,
                status_code=response.status_code,
            )
            return BootstrapResult.fail(
                CasdoorBootstrapErrorCode.CASDOOR_API_ERROR,
                f"Casdoor returned HTTP {response.status_code} on {endpoint.value}",
                endpoint=endpoint.value,
            )

        parsed_res = self._parse_json_object(response, endpoint)
        if not parsed_res.is_ok or parsed_res.value is None:
            return BootstrapResult(error=parsed_res.error)

        parsed = parsed_res.value
        if parsed.get("status") == _CASDOOR_STATUS_ERROR:
            msg = str(parsed.get("msg") or "unknown Casdoor error")
            logger.error("casdoor_api_domain_error", endpoint=endpoint.value, message=msg)
            return BootstrapResult.fail(
                CasdoorBootstrapErrorCode.CASDOOR_API_ERROR,
                f"Casdoor API error on {endpoint.value}: {msg}",
                endpoint=endpoint.value,
            )
        return BootstrapResult.ok(parsed)

    def _casdoor_json_request(
        self,
        method: str,
        endpoint: CasdoorBootstrapEndpoint,
        *,
        params: Mapping[str, str] | None = None,
        json_body: Mapping[str, object] | None = None,
    ) -> BootstrapResult[dict[str, object]]:
        url = f"{self._base_url}{endpoint.value}"
        resp_res = self._http.request(
            method,
            url,
            params=params,
            json=json_body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        return self._handle_casdoor_response(resp_res, endpoint)

    def _casdoor_form_request(
        self,
        method: str,
        endpoint: CasdoorBootstrapEndpoint,
        *,
        params: Mapping[str, str] | None = None,
        form_data: Mapping[str, str],
    ) -> BootstrapResult[dict[str, object]]:
        url = f"{self._base_url}{endpoint.value}"
        resp_res = self._http.request(
            method,
            url,
            params=params,
            data=form_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        return self._handle_casdoor_response(resp_res, endpoint)

    def _ensure_organization(
        self,
        *,
        name: str,
        display_name: str,
        default_application: str,
    ) -> BootstrapResult[None]:
        existing_res = self._casdoor_json_request(
            "GET",
            CasdoorBootstrapEndpoint.GET_ORGANIZATION,
            params={"id": f"{_CASDOOR_ADMIN_OWNER}/{name}"},
        )
        if not existing_res.is_ok or existing_res.value is None:
            return BootstrapResult(error=existing_res.error)

        existing_org = existing_res.value.get("data")
        if isinstance(existing_org, dict):
            needs_update = (
                existing_org.get("defaultApplication") != default_application
                or existing_org.get("passwordType") != CasdoorConstants.PASSWORD_TYPE
                or existing_org.get("enableSoftDeletion") is not True
            )
            if needs_update:
                org_doc = {str(k): v for k, v in existing_org.items()}
                org_doc["defaultApplication"] = default_application
                org_doc["passwordType"] = CasdoorConstants.PASSWORD_TYPE
                org_doc["enableSoftDeletion"] = True
                update_res = self._casdoor_json_request(
                    "POST",
                    CasdoorBootstrapEndpoint.UPDATE_ORGANIZATION,
                    params={"id": f"{_CASDOOR_ADMIN_OWNER}/{name}"},
                    json_body=org_doc,
                )
                if not update_res.is_ok:
                    return BootstrapResult(error=update_res.error)
                logger.info(
                    "casdoor_org_updated",
                    organization=name,
                    default_application=default_application,
                )
            else:
                logger.info("casdoor_org_unchanged", organization=name)
            return BootstrapResult.ok(None)

        create_res = self._casdoor_json_request(
            "POST",
            CasdoorBootstrapEndpoint.ADD_ORGANIZATION,
            json_body={
                "owner": _CASDOOR_ADMIN_OWNER,
                "name": name,
                "displayName": display_name,
                "defaultApplication": default_application,
                "passwordType": CasdoorConstants.PASSWORD_TYPE,
                "passwordSalt": "",
                "defaultAvatar": CasdoorConstants.DEFAULT_AVATAR_URL,
                "initScore": 0,
                "languages": [CasdoorConstants.DEFAULT_LANGUAGE],
                "enableSoftDeletion": True,
            },
        )
        if not create_res.is_ok:
            return BootstrapResult(error=create_res.error)
        logger.info(
            "casdoor_org_created",
            organization=name,
            default_application=default_application,
        )
        return BootstrapResult.ok(None)

    def _ensure_application(
        self,
        spec: CasdoorApplicationSpec,
    ) -> BootstrapResult[CasdoorClientCredentials]:
        existing_res = self._casdoor_json_request(
            "GET",
            CasdoorBootstrapEndpoint.GET_APPLICATION,
            params={"id": f"{_CASDOOR_ADMIN_OWNER}/{spec.name.value}"},
        )
        if not existing_res.is_ok or existing_res.value is None:
            return BootstrapResult(error=existing_res.error)

        desired_grants = [grant.value for grant in spec.grant_types]
        desired_redirects = list(spec.redirect_uris)
        desired_token_fields = list(CasdoorConstants.MINIMAL_TOKEN_FIELDS)

        existing_data = existing_res.value.get("data")
        if isinstance(existing_data, dict) and existing_data.get("clientId"):
            desired_fields: dict[str, object] = {
                "displayName": spec.display_name,
                "organization": spec.organization,
                "tokenFormat": CasdoorTokenFormat.JWT_CUSTOM.value,
                "tokenFields": desired_token_fields,
                "redirectUris": desired_redirects,
                "isShared": spec.is_shared,
                "enablePassword": spec.enable_password,
                "enableSignUp": spec.enable_sign_up,
                "enableCodeSignin": False,
                "enableWebAuthn": spec.enable_webauthn,
                "grantTypes": desired_grants,
                "expireInHours": CasdoorConstants.TOKEN_EXPIRE_HOURS,
                "refreshExpireInHours": CasdoorConstants.REFRESH_TOKEN_EXPIRE_HOURS,
            }
            app_doc = {str(k): v for k, v in existing_data.items()}
            needs_update = any(app_doc.get(key) != val for key, val in desired_fields.items())
            if needs_update:
                app_doc.update(desired_fields)
                update_res = self._casdoor_json_request(
                    "POST",
                    CasdoorBootstrapEndpoint.UPDATE_APPLICATION,
                    params={"id": f"{_CASDOOR_ADMIN_OWNER}/{spec.name.value}"},
                    json_body=app_doc,
                )
                if not update_res.is_ok:
                    return BootstrapResult(error=update_res.error)
                logger.info(
                    "casdoor_app_updated",
                    application=spec.name.value,
                    grant_types=desired_grants,
                )
            else:
                logger.info("casdoor_app_unchanged", application=spec.name.value)
            return BootstrapResult.ok(
                CasdoorClientCredentials(
                    client_id=str(app_doc["clientId"]),
                    client_secret=str(app_doc.get("clientSecret") or ""),
                )
            )

        client_id = f"{spec.name.value.replace('-', '_')}_{self._token_hex(6)}"
        client_secret = self._token_hex(24)
        create_res = self._casdoor_json_request(
            "POST",
            CasdoorBootstrapEndpoint.ADD_APPLICATION,
            json_body={
                "owner": _CASDOOR_ADMIN_OWNER,
                "name": spec.name.value,
                "displayName": spec.display_name,
                "organization": spec.organization,
                "cert": CasdoorConstants.DEFAULT_CERT_NAME,
                "enablePassword": spec.enable_password,
                "enableSignUp": spec.enable_sign_up,
                "enableCodeSignin": False,
                "enableWebAuthn": spec.enable_webauthn,
                "isShared": spec.is_shared,
                "clientId": client_id,
                "clientSecret": client_secret,
                "redirectUris": desired_redirects,
                "tokenFormat": CasdoorTokenFormat.JWT_CUSTOM.value,
                "tokenFields": desired_token_fields,
                "expireInHours": CasdoorConstants.TOKEN_EXPIRE_HOURS,
                "refreshExpireInHours": CasdoorConstants.REFRESH_TOKEN_EXPIRE_HOURS,
                "grantTypes": desired_grants,
            },
        )
        if not create_res.is_ok:
            return BootstrapResult(error=create_res.error)
        logger.info("casdoor_app_created", application=spec.name.value, client_id=client_id)
        return BootstrapResult.ok(
            CasdoorClientCredentials(client_id=client_id, client_secret=client_secret)
        )

    def _ensure_platform_admin_user(self, initial_password: str) -> BootstrapResult[str]:
        organization = self._config.platform_realm
        username = CasdoorConstants.PLATFORM_ADMIN_USERNAME
        user_lookup = f"{organization}/{username}"

        existing_res = self._casdoor_json_request(
            "GET",
            CasdoorBootstrapEndpoint.GET_USER,
            params={"id": user_lookup},
        )
        if not existing_res.is_ok or existing_res.value is None:
            return BootstrapResult(error=existing_res.error)

        existing_data = existing_res.value.get("data")
        if isinstance(existing_data, dict) and existing_data.get("id"):
            user_id = str(existing_data["id"])
            logger.info(
                "casdoor_platform_admin_exists",
                organization=organization,
                username=username,
                user_id=user_id,
            )
            return BootstrapResult.ok(user_id)

        create_res = self._casdoor_json_request(
            "POST",
            CasdoorBootstrapEndpoint.ADD_USER,
            json_body={
                "owner": organization,
                "name": username,
                "displayName": CasdoorConstants.PLATFORM_ADMIN_DISPLAY_NAME,
                "email": self._config.platform_admin_email,
                "emailVerified": True,
                "password": initial_password,
                "type": CasdoorConstants.DEFAULT_USER_TYPE,
                "isAdmin": True,
                "isForbidden": False,
            },
        )
        if not create_res.is_ok:
            return BootstrapResult(error=create_res.error)

        created_res = self._casdoor_json_request(
            "GET",
            CasdoorBootstrapEndpoint.GET_USER,
            params={"id": user_lookup},
        )
        if not created_res.is_ok or created_res.value is None:
            return BootstrapResult(error=created_res.error)

        created_data = created_res.value.get("data")
        if not isinstance(created_data, dict) or not created_data.get("id"):
            return BootstrapResult.fail(
                CasdoorBootstrapErrorCode.CASDOOR_API_ERROR,
                f"Casdoor created user {user_lookup} without returning an id.",
                endpoint=CasdoorBootstrapEndpoint.GET_USER.value,
            )

        user_id = str(created_data["id"])
        logger.info(
            "casdoor_platform_admin_created",
            organization=organization,
            username=username,
            user_id=user_id,
        )
        return BootstrapResult.ok(user_id)


# ── Composition Root / CLI Entrypoint ─────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint invoked by CI/CD after `infra/cloud/aws/casdoor` rollout."""
    parser = argparse.ArgumentParser(
        description="Idempotently bootstrap cloud Casdoor realms, OAuth apps, and AWS Secrets Manager."
    )
    parser.add_argument(
        "--env",
        required=True,
        help="Target Pulumi stack environment (e.g., staging, prod).",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", CasdoorConstants.DEFAULT_AWS_REGION),
        help="AWS region for Secrets Manager calls.",
    )
    parser.add_argument(
        "--platform-admin-email",
        default="",
        help="Optional override for the initial platform_admin operator email.",
    )
    args = parser.parse_args(argv)

    config_res = resolve_bootstrap_config(
        env_name=args.env,
        platform_admin_email_override=args.platform_admin_email,
    )
    if not config_res.is_ok or config_res.value is None:
        logger.error(
            "casdoor_cloud_bootstrap_config_error",
            code=config_res.error.code.value if config_res.error else "UNKNOWN",
            detail=config_res.error.detail if config_res.error else "Unknown config error",
        )
        return 1

    sm_client = boto3.client("secretsmanager", region_name=args.region)
    secrets_store = AwsSecretsManagerAdapter(sm_client)

    with httpx.Client(
        timeout=httpx.Timeout(CasdoorConstants.BOOTSTRAP_HTTP_TIMEOUT_SECONDS, connect=5.0),
        verify=True,
        follow_redirects=False,
    ) as raw_client:
        bootstrapper = CasdoorCloudBootstrapper(
            config=config_res.value,
            http_client=HttpxClientAdapter(raw_client),
            secrets_store=secrets_store,
        )
        result = bootstrapper.run()

    if not result.is_ok:
        logger.error(
            "casdoor_cloud_bootstrap_failed",
            code=result.error.code.value if result.error else "UNKNOWN",
            detail=result.error.detail if result.error else "Unknown bootstrap failure",
            endpoint=result.error.endpoint if result.error else "",
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
