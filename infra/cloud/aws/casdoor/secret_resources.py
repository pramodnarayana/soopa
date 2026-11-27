"""AWS Secrets Manager resources for the Casdoor Identity Provider."""

from __future__ import annotations

from dataclasses import dataclass

import pulumi
import pulumi_aws as aws
import pulumi_random as random
from constants import CasdoorConstants


@dataclass(frozen=True)
class CasdoorSecretsBundle:
    """Strongly typed bundle of Secrets Manager resources provisioned for Casdoor."""

    admin_password_secret: aws.secretsmanager.Secret
    db_password_secret: aws.secretsmanager.Secret
    dsn_secret: aws.secretsmanager.Secret
    admin_oauth_secret: aws.secretsmanager.Secret


def build_casdoor_postgres_dsn(
    endpoint: str,
    password: str,
    *,
    username: str = CasdoorConstants.DB_USER,
    db_name: str = CasdoorConstants.DB_NAME,
) -> str:
    """Build a validated libpq DSN string for Casdoor using the least-privilege ``casdoor_app`` role."""
    cleaned = endpoint.strip()
    if ":" in cleaned:
        host, _, port = cleaned.rpartition(":")
    else:
        host, port = cleaned, CasdoorConstants.DEFAULT_DB_PORT

    host = host.strip()
    port = port.strip() or CasdoorConstants.DEFAULT_DB_PORT
    if not host:
        raise ValueError("Casdoor PostgreSQL endpoint host must not be empty.")
    if not port.isdigit():
        raise ValueError(f"Invalid Casdoor PostgreSQL port '{port}' in endpoint '{endpoint}'.")

    return f"user={username} password={password} host={host} port={port} sslmode=require dbname={db_name}"


def provision_secrets(
    prefix: str,
    tags: dict[str, str],
    *,
    global_db_endpoint: pulumi.Input[str],
    secret_recovery_window_days: int = CasdoorConstants.DEFAULT_SECRET_RECOVERY_WINDOW_DAYS,
) -> CasdoorSecretsBundle:
    """Provision Casdoor admin password, dedicated DB role password, DSN, and OAuth M2M secrets."""
    casdoor_admin_password = random.RandomPassword(
        "casdoor-admin-password",
        length=32,
        special=True,
        override_special="!@#$%^&*()-_=+",
    )

    admin_password_secret = aws.secretsmanager.Secret(
        f"{prefix}casdoor-admin-password-secret",
        name_prefix=f"platform/{prefix}casdoor-admin-password-",
        recovery_window_in_days=secret_recovery_window_days,
        tags=tags,
    )
    aws.secretsmanager.SecretVersion(
        f"{prefix}casdoor-admin-password-secret-val",
        secret_id=admin_password_secret.id,
        secret_string=casdoor_admin_password.result,
    )

    # Dedicated least-privilege PostgreSQL password for `casdoor_app` (never RDS master password).
    # Special characters exclude spaces/quotes/backslashes so libpq key=value DSN stays safe.
    casdoor_db_password = random.RandomPassword(
        "casdoor-db-password",
        length=32,
        special=True,
        override_special="!#*_-=",
    )
    db_password_secret = aws.secretsmanager.Secret(
        f"{prefix}casdoor-db-password-secret",
        name_prefix=f"platform/{prefix}casdoor-db-password-",
        recovery_window_in_days=secret_recovery_window_days,
        tags=tags,
    )
    aws.secretsmanager.SecretVersion(
        f"{prefix}casdoor-db-password-secret-val",
        secret_id=db_password_secret.id,
        secret_string=casdoor_db_password.result,
    )

    # Full PostgreSQL DSN stored in Secrets Manager so the DB password NEVER appears
    # in plaintext ECS Task Definition `environment` JSON.
    dsn_secret = aws.secretsmanager.Secret(
        f"{prefix}casdoor-dsn-secret",
        name_prefix=f"platform/{prefix}casdoor-dsn-",
        recovery_window_in_days=secret_recovery_window_days,
        tags=tags,
    )
    aws.secretsmanager.SecretVersion(
        f"{prefix}casdoor-dsn-secret-val",
        secret_id=dsn_secret.id,
        secret_string=pulumi.Output.all(global_db_endpoint, casdoor_db_password.result).apply(
            lambda args: build_casdoor_postgres_dsn(args[0], args[1])
        ),
    )

    # Populated by the post-deploy bootstrap job with Casdoor M2M admin client credentials JSON
    admin_oauth_secret = aws.secretsmanager.Secret(
        f"{prefix}casdoor-admin-oauth-secret",
        name_prefix=f"platform/{prefix}casdoor-admin-oauth-",
        recovery_window_in_days=secret_recovery_window_days,
        tags=tags,
    )

    return CasdoorSecretsBundle(
        admin_password_secret=admin_password_secret,
        db_password_secret=db_password_secret,
        dsn_secret=dsn_secret,
        admin_oauth_secret=admin_oauth_secret,
    )
