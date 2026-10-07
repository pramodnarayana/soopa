import os

from seedwork.infra.config_models import PlatformAwsSettings

from storage.adapters.s3_storage_adapter import Aioboto3PayloadStorage
from storage.ports.payload_storage_port import PayloadStoragePort


class StorageProvider:
    @staticmethod
    def create_payload_storage(bucket: str | None = None) -> PayloadStoragePort:
        """
        Creates a PayloadStoragePort using platform environment variables.
        """
        aws_settings = PlatformAwsSettings()
        # Fallback to S3_BUCKET if not provided
        bucket_name = bucket or os.getenv("S3_BUCKET", "edi-as2-payloads")

        # Override endpoint url from S3_ENDPOINT_URL if present
        s3_endpoint = os.getenv("S3_ENDPOINT_URL")
        if not s3_endpoint:
            s3_endpoint = aws_settings.endpoint_url

        # Optional credentials from S3_* config if distinct from AWS_*
        access_key = os.getenv("S3_ACCESS_KEY_ID") or aws_settings.access_key_id
        secret_key = os.getenv("S3_SECRET_ACCESS_KEY") or aws_settings.secret_access_key

        region = os.getenv("S3_REGION") or aws_settings.resolved_region

        return Aioboto3PayloadStorage(
            bucket=bucket_name,
            region=region,
            endpoint_url=s3_endpoint,
            access_key_id=access_key,
            secret_access_key=secret_key,
        )
