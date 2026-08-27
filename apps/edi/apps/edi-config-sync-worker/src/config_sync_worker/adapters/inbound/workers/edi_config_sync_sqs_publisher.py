import json
import os
from types import TracebackType

import aioboto3
import structlog
from edi.adapters.aws.aws_types import SQSClientContextProtocol, SQSClientProtocol

from config_sync_worker.ports.outbound.outbox_port import OutboxPort

logger = structlog.get_logger(__name__)


class EdiConfigSyncSqsPublisher(OutboxPort):
    def __init__(
        self,
        queue_name: str = "edi-config-sync.fifo",
        endpoint_url: str | None = None,
        region: str | None = None,
    ):
        self.queue_name = queue_name
        self.endpoint_url = endpoint_url or os.environ.get("AWS_ENDPOINT_URL")
        # Fallback for local development if missing
        if not self.endpoint_url and os.environ.get("ENVIRONMENT") == "local":
            self.endpoint_url = "http://localhost:4566"
        self.region = region or "us-east-1"
        self.session = aioboto3.Session()
        self._client: SQSClientProtocol | None = None
        self._client_context: SQSClientContextProtocol | None = None
        self._queue_url: str | None = None

    async def __aenter__(self) -> "EdiConfigSyncSqsPublisher":
        if not self._client:
            self._client_context = self.session.client(
                "sqs", endpoint_url=self.endpoint_url, region_name=self.region
            )
            self._client = await self._client_context.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._client_context:
            await self._client_context.__aexit__(exc_type, exc_val, exc_tb)
            self._client = None
            self._client_context = None

    async def close(self) -> None:
        """Close the adapter and release all resources."""
        if self._client_context:
            await self._client_context.__aexit__(None, None, None)
            self._client = None
            self._client_context = None

    async def _get_queue_url(self, sqs: SQSClientProtocol) -> str:
        if self._queue_url:
            return self._queue_url
        try:
            queue_url_response = await sqs.get_queue_url(QueueName=self.queue_name)
            self._queue_url = queue_url_response["QueueUrl"]
            return self._queue_url
        except Exception:
            logger.exception("sqs_queue_url_resolution_failed", queue_name=self.queue_name)
            raise

    async def publish_event(
        self,
        event_type: str,
        payload: dict[str, object],
        idempotency_key: str,
        tenant_id: str,
    ) -> None:
        """Publishes an event to the outbox queue."""
        if not self._client:
            await self.__aenter__()

        sqs = self._client
        if not sqs:
            raise RuntimeError("SQS client not initialized")

        queue_url = await self._get_queue_url(sqs)

        message_body = json.dumps(
            {
                **(payload or {}),
                "tenant_id": tenant_id,
                "event_type": event_type,
                "idempotency_key": idempotency_key,
            }
        )

        await sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=message_body,
            MessageGroupId=tenant_id,
            MessageDeduplicationId=idempotency_key,
        )
        logger.info(
            "sqs_event_published",
            event_type=event_type,
            tenant_id=tenant_id,
            queue_name=self.queue_name,
        )
