from enum import StrEnum


class SecretCategory(StrEnum):
    """
    Strict architectural categories for AWS Secrets Manager.
    These map to specific subdirectories in the Fargate Sidecar pattern.
    """

    AS2_KEY = "as2_key"
    CERTIFICATE = "certificate"
    CREDENTIAL = "credential"


# Shared absolute path for the tmpfs Fargate secrets volume
SECRETS_MOUNT_PATH = "/mnt/secrets"
