import asyncio
import os
import sys
from typing import Any

import boto3  # type: ignore[import-untyped]
import structlog
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)


from pipeline.ports.secret_store import SecretStorePort


class AwsSecretsManagerSecretStore(SecretStorePort):
    """
    Adapter for AWS Secrets Manager. Replaces HashiCorp Vault.
    Uses LocalStack endpoints in development and native IAM in production.
    """

    def __init__(self) -> None:
        env = os.getenv("ENVIRONMENT", "production")
        if env in ("development", "dev", "test", "local") or "pytest" in sys.modules:
            endpoint_url = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
            self.client = boto3.client(
                "secretsmanager",
                endpoint_url=endpoint_url,
                region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
            )
        else:
            self.client = boto3.client(
                "secretsmanager", region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1")
            )

    async def get_secret(self, vault_ref: str) -> str:
        """
        Retrieves a secret from AWS Secrets Manager asynchronously.
        Boto3 is synchronous, so we wrap it in asyncio.to_thread.
        """

        def _fetch() -> str:
            try:
                response = self.client.get_secret_value(SecretId=vault_ref)
                secret_string = response.get("SecretString")
                if not secret_string:
                    raise ValueError(f"Secret string is empty for {vault_ref}")
                return str(secret_string)
            except ClientError as e:
                logger.exception("failed_to_fetch_secret", error=str(e), vault_ref=vault_ref)
                raise ValueError(f"Secret not found or accessible at path: {vault_ref}") from e

        return await asyncio.to_thread(_fetch)

    async def store_private_key(self, private_key_pem: bytes, category: Any = None) -> str:
        """
        Stores a private key in AWS Secrets Manager and returns the secret reference.
        """

        def _store() -> str:
            import uuid

            secret_name = f"private-key-{uuid.uuid4()}"
            try:
                self.client.create_secret(
                    Name=secret_name, SecretString=private_key_pem.decode("utf-8")
                )
                logger.info("stored_private_key", secret_name=secret_name)
                return secret_name
            except ClientError as e:
                logger.exception("failed_to_store_private_key", error=str(e))
                raise ValueError(f"Failed to store private key: {e}") from e

        return await asyncio.to_thread(_store)

    async def retrieve_secret(self, vault_ref: str) -> bytes:
        val = await self.get_secret(vault_ref)
        return val.encode("utf-8")

    async def retrieve_private_key(self, vault_ref: str) -> bytes:
        return await self.retrieve_secret(vault_ref)

    async def delete_secret(self, vault_ref: str) -> None:
        """
        Deletes a secret from AWS Secrets Manager by vault_ref.
        """

        def _delete() -> None:
            try:
                self.client.delete_secret(SecretId=vault_ref, ForceDeleteWithoutRecovery=True)
                logger.info("deleted_secret", vault_ref=vault_ref)
            except ClientError as e:
                logger.exception("failed_to_delete_secret", error=str(e), vault_ref=vault_ref)
                raise ValueError(f"Failed to delete secret at {vault_ref}: {e}") from e

        await asyncio.to_thread(_delete)
