import json
from typing import Any, ClassVar, Self

import aioboto3
import structlog
from database.events import EventEnvelope
from database.outbox_serializer import serialize_domain_event
from outbox.ports.outbox_publisher_port import OutboxPublisherPort

logger = structlog.get_logger(__name__)


class AwsBatchPublisherBase(OutboxPublisherPort):
    """Shared AWS publisher lifecycle, serialization, batching, and FIFO handling."""

    service_name: ClassVar[str]
    destination_parameter: ClassVar[str]
    single_method: ClassVar[str]
    batch_method: ClassVar[str]
    batch_entries_parameter: ClassVar[str]
    message_parameter: ClassVar[str]
    destination_error: ClassVar[str]

    def __init__(
        self,
        destination: str,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
    ) -> None:
        self.destination = destination
        self.region_name = region_name
        self.endpoint_url = endpoint_url
        self.session = aioboto3.Session()
        self._client: Any = None
        self._client_context: Any = None

    async def __aenter__(self) -> Self:
        if not self._client:
            self._client_context = self.session.client(
                self.service_name,
                region_name=self.region_name,
                endpoint_url=self.endpoint_url,
            )
            self._client = await self._client_context.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._client_context:
            await self._client_context.__aexit__(exc_type, exc_val, exc_tb)
            self._client = None
            self._client_context = None

    @property
    def is_fifo(self) -> bool:
        return self.destination.endswith(".fifo")

    def _validate_destination(self) -> None:
        if not self.destination:
            raise ValueError(self.destination_error)

    def _build_entry(self, event: EventEnvelope, entry_id: str, *, batch: bool) -> dict[str, Any]:
        entry: dict[str, Any] = {
            self.message_parameter: json.dumps(serialize_domain_event(event)),
        }
        if batch:
            entry["Id"] = entry_id
        if self.is_fifo:
            entry["MessageGroupId"] = event.tenant_id or "default"
            entry["MessageDeduplicationId"] = event.idempotency_key or event.id
        return entry

    async def _publish_one(self, client: Any, event: EventEnvelope) -> None:
        params = {
            self.destination_parameter: self.destination,
            **self._build_entry(event, "0", batch=False),
        }
        await getattr(client, self.single_method)(**params)
        logger.debug(
            "aws_event_published",
            service=self.service_name,
            destination=self.destination,
            event_type=event.event_type,
        )

    async def publish(self, event: EventEnvelope) -> None:
        self._validate_destination()
        try:
            if self._client:
                await self._publish_one(self._client, event)
            else:
                async with self.session.client(
                    self.service_name,
                    region_name=self.region_name,
                    endpoint_url=self.endpoint_url,
                ) as client:
                    await self._publish_one(client, event)
        except Exception:
            logger.exception(
                "aws_publish_failed",
                service=self.service_name,
                destination=self.destination,
                event_id=event.id,
            )
            raise

    async def _publish_batch_internal(self, client: Any, events: list[EventEnvelope]) -> list[str]:
        successful_ids: list[str] = []
        first_transport_error: Exception | None = None

        for offset in range(0, len(events), 10):
            chunk = events[offset : offset + 10]
            entry_id_to_event_id = {str(index): event.id for index, event in enumerate(chunk)}
            entries = [
                self._build_entry(event, str(index), batch=True)
                for index, event in enumerate(chunk)
            ]
            params = {
                self.destination_parameter: self.destination,
                self.batch_entries_parameter: entries,
            }

            try:
                response = await getattr(client, self.batch_method)(**params)
            except Exception as exc:
                logger.exception(
                    "aws_batch_publish_chunk_failed",
                    service=self.service_name,
                    destination=self.destination,
                )
                first_transport_error = first_transport_error or exc
                if self.is_fifo:
                    break
                continue

            for success in response.get("Successful", []):
                successful_ids.append(entry_id_to_event_id[success["Id"]])

            failed_entries = response.get("Failed", [])
            for failed in failed_entries:
                logger.error(
                    "aws_batch_publish_entry_failed",
                    service=self.service_name,
                    destination=self.destination,
                    event_id=entry_id_to_event_id[failed["Id"]],
                    code=failed.get("Code"),
                    message=failed.get("Message"),
                )
            if failed_entries and self.is_fifo:
                break

        if not successful_ids and first_transport_error is not None:
            raise first_transport_error
        return successful_ids

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        self._validate_destination()
        if not events:
            return []

        try:
            if self._client:
                return await self._publish_batch_internal(self._client, events)
            async with self.session.client(
                self.service_name,
                region_name=self.region_name,
                endpoint_url=self.endpoint_url,
            ) as client:
                return await self._publish_batch_internal(client, events)
        except Exception:
            logger.exception(
                "aws_publish_batch_failed",
                service=self.service_name,
                destination=self.destination,
            )
            raise
