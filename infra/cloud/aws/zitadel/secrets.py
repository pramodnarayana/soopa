import pulumi
import pulumi_aws as aws
import pulumi_random as random


def provision_secrets(prefix: str, tags: dict):
    # Zitadel requires a masterkey (32 bytes)
    zitadel_masterkey = random.RandomPassword(
        "zitadel-masterkey",
        length=32,
    )

    zitadel_admin_password = random.RandomPassword(
        "zitadel-admin-password",
        length=32,
        special=True,
        override_special="!@#$%^&*()-_=+",
    )

    is_prod = pulumi.get_stack() == "production"

    zitadel_masterkey_secret = aws.secretsmanager.Secret(
        f"{prefix}zitadel-masterkey-secret",
        name_prefix=f"platform/{prefix}zitadel-masterkey-",
        recovery_window_in_days=30 if is_prod else 0,
        tags=tags,
    )

    aws.secretsmanager.SecretVersion(
        f"{prefix}zitadel-masterkey-secret-val",
        secret_id=zitadel_masterkey_secret.id,
        secret_string=zitadel_masterkey.result,
    )

    zitadel_machinekey_secret = aws.secretsmanager.Secret(
        f"{prefix}zitadel-machinekey-secret",
        name_prefix=f"platform/{prefix}zitadel-machinekey-",
        recovery_window_in_days=30 if is_prod else 0,
        tags=tags,
    )
    # Intentionally DO NOT create a SecretVersion here for the MachineKey.
    # The Sidecar container will generate the JSON and PutSecretValue directly to this Secret ARN.

    zitadel_admin_password_secret = aws.secretsmanager.Secret(
        f"{prefix}zitadel-admin-password-secret",
        name_prefix=f"platform/{prefix}zitadel-admin-password-",
        recovery_window_in_days=30 if is_prod else 0,
        tags=tags,
    )

    aws.secretsmanager.SecretVersion(
        f"{prefix}zitadel-admin-password-secret-val",
        secret_id=zitadel_admin_password_secret.id,
        secret_string=zitadel_admin_password.result,
    )

    return (
        zitadel_masterkey,
        zitadel_admin_password,
        zitadel_masterkey_secret,
        zitadel_machinekey_secret,
        zitadel_admin_password_secret,
    )
