"""AWS Secrets Manager resources for the Casdoor Identity Provider."""

from __future__ import annotations

import pulumi
import pulumi_aws as aws
import pulumi_random as random
from constants import CasdoorConstants
from infra_seedwork import DatabaseConstants


def provision_secrets(
    prefix: str,
    tags: dict[str, str],
    *,
    global_db_endpoint: pulumi.Input[str],
    global_db_password: pulumi.Input[str],
    secret_recovery_window_days: int = 0,
) -> tuple[
    random.RandomPassword,
    aws.secretsmanager.Secret,
    aws.secretsmanager.Secret,
    aws.secretsmanager.Secret,
]:
    """Provision Casdoor admin password, PostgreSQL DSN, and OAuth M2M admin secrets."""
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
        secret_string=pulumi.Output.all(global_db_endpoint, global_db_password).apply(
            lambda args: (
                f"user={DatabaseConstants.MASTER_USERNAME} password={args[1]} "
                f"host={args[0].split(':')[0]} port={args[0].split(':')[1]} "
                f"sslmode=require dbname={CasdoorConstants.DB_NAME}"
            )
        ),
    )

    # Populated by the post-deploy bootstrap job with Casdoor M2M admin client credentials JSON
    admin_oauth_secret = aws.secretsmanager.Secret(
        f"{prefix}casdoor-admin-oauth-secret",
        name_prefix=f"platform/{prefix}casdoor-admin-oauth-",
        recovery_window_in_days=secret_recovery_window_days,
        tags=tags,
    )

    return casdoor_admin_password, admin_password_secret, dsn_secret, admin_oauth_secret
