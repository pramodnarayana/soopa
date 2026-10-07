import pulumi
import pulumi_aws as aws
import pulumi_random as random
from constants import OpenObserveConstants


def provision_openobserve_foundations(
    prefix: str,
    tags: dict,
):
    obs_bucket = aws.s3.Bucket(
        f"{prefix}observability-data",
        bucket=f"{prefix}observability-data",
        force_destroy=True,
        tags=tags,
    )

    obs_user_password = random.RandomPassword(
        "openobserve-password",
        length=32,
        special=False,
    )

    is_prod = pulumi.get_stack() == "production"

    obs_user_secret = aws.secretsmanager.Secret(
        f"{prefix}obs-user-secret",
        name_prefix=f"platform/{prefix}openobserve-user-",
        recovery_window_in_days=30 if is_prod else 0,
        tags=tags,
    )

    aws.secretsmanager.SecretVersion(
        f"{prefix}obs-user-secret-val",
        secret_id=obs_user_secret.id,
        secret_string=OpenObserveConstants.DEFAULT_ADMIN_EMAIL,
    )

    obs_password_secret = aws.secretsmanager.Secret(
        f"{prefix}obs-password-secret",
        name_prefix=f"platform/{prefix}openobserve-password-",
        recovery_window_in_days=30 if is_prod else 0,
        tags=tags,
    )

    aws.secretsmanager.SecretVersion(
        f"{prefix}obs-password-secret-val",
        secret_id=obs_password_secret.id,
        secret_string=obs_user_password.result,
    )

    return obs_bucket, obs_user_secret.arn, obs_password_secret.arn
