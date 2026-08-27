import json
from typing import Any

import aioboto3
import structlog
from database.events import EventEnvelope
from database.outbox_serializer import serialize_domain_event
from outbox.ports.outbox_publisher_port import OutboxPublisherPort

from edi.domain.events import PIPELINE_EVENT_ROUTING_MAP

logger = structlog.get_logger(__name__)


class EdiDataPlaneSqsOutboxPublisherAdapter(OutboxPublisherPort):
    def __init__(self, endpoint_url: str | None = None, region: str = "us-east-1"):
        self.endpoint_url = endpoint_url
        self.region = region
        self.session = aioboto3.Session()
        self._queue_url_cache: dict[str, str] = {}
        self._sqs_client: Any = None
        self._client_context: Any = None

    async def __aenter__(self) -> "EdiDataPlaneSqsOutboxPublisherAdapter":
        """Allows using the publisher as a context manager for batch publishing."""
        if not self._sqs_client:
            self._client_context = self.session.client(
                "sqs", endpoint_url=self.endpoint_url, region_name=self.region
            )
            self._sqs_client = await self._client_context.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._client_context:
            await self._client_context.__aexit__(exc_type, exc_val, exc_tb)
            self._sqs_client = None
            self._client_context = None

    async def _send_batch_chunk(
        self,
        queue_name: str,
        queue_url: str,
        sqs: Any,
        events: list[EventEnvelope],
    ) -> list[str]:
        entries = []
        entry_id_to_event_id = {}

        for idx, event in enumerate(events):
            entry_id = str(idx)
            entry_id_to_event_id[entry_id] = event.id
            message = serialize_domain_event(event)

            entry: dict[str, Any] = {
                "Id": entry_id,
                "MessageBody": json.dumps(message),
            }
            if queue_name.endswith(".fifo"):
                entry["MessageGroupId"] = event.tenant_id or "default"
                entry["MessageDeduplicationId"] = event.idempotency_key or event.id
            entries.append(entry)

        if not entries:
            return []

        successful_ids = []
        try:
            resp = await sqs.send_message_batch(QueueUrl=queue_url, Entries=entries)
            for success in resp.get("Successful", []):
                successful_ids.append(entry_id_to_event_id[success["Id"]])
            for failed in resp.get("Failed", []):
                logger.error(
                    "edi_data_plane_batch_forward_failed",
                    failedId=failed["Id"],
                    event_id=entry_id_to_event_id[failed["Id"]],
                    failedMessage=failed.get("Message"),
                )
        except Exception:
            logger.exception("edi_data_plane_batch_send_failed", queue_name=queue_name)

        return successful_ids

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        if not events:
            return []

        successful_ids = []

        async def _do_publish_batch(sqs: Any) -> None:
            batches_by_queue: dict[str, list[EventEnvelope]] = {}

            for event in events:
                queue_name = PIPELINE_EVENT_ROUTING_MAP.get(event.event_type)
                if not queue_name:
                    logger.warning(
                        "data_plane_outbox.unknown_event_type_skipped",
                        event_id=event.id,
                        event_type=event.event_type,
                    )
                    continue
                batches_by_queue.setdefault(queue_name, []).append(event)

            for queue_name, queue_events in batches_by_queue.items():
                if queue_name not in self._queue_url_cache:
                    try:
                        resp = await sqs.get_queue_url(QueueName=queue_name)
                        self._queue_url_cache[queue_name] = resp["QueueUrl"]
                    except Exception:
                        logger.exception(
                            "edi_data_plane_queue_url_resolution_failed", queue_name=queue_name
                        )
                        continue

                queue_url = self._queue_url_cache[queue_name]

                # SQS allows max 10 messages per batch
                for i in range(0, len(queue_events), 10):
                    batch = queue_events[i : i + 10]
                    successful_ids.extend(
                        await self._send_batch_chunk(queue_name, queue_url, sqs, batch)
                    )

        if self._sqs_client:
            await _do_publish_batch(self._sqs_client)
        else:
            async with self.session.client(
                "sqs", endpoint_url=self.endpoint_url, region_name=self.region
            ) as sqs:
                await _do_publish_batch(sqs)

        return successful_ids

    async def publish(self, event: EventEnvelope) -> None:
        """Publishes a single message, optionally reusing the active connection."""
        queue_name = PIPELINE_EVENT_ROUTING_MAP.get(event.event_type)
        if not queue_name:
            raise ValueError(f"Unknown event_type: {event.event_type} - cannot resolve queue.")

        async def _do_publish(sqs: Any) -> None:
            if queue_name not in self._queue_url_cache:
                try:
                    resp = await sqs.get_queue_url(QueueName=queue_name)
                    self._queue_url_cache[queue_name] = resp["QueueUrl"]
                except Exception:
                    logger.exception(
                        "edi_data_plane_queue_url_resolution_failed", queue_name=queue_name
                    )
                    raise

            queue_url = self._queue_url_cache[queue_name]
            message = serialize_domain_event(event)

            try:
                kwargs: dict[str, Any] = {
                    "QueueUrl": queue_url,
                    "MessageBody": json.dumps(message),
                }
                if queue_name.endswith(".fifo"):
                    kwargs["MessageGroupId"] = event.tenant_id or "default"
                    kwargs["MessageDeduplicationId"] = event.idempotency_key or event.id

                await sqs.send_message(**kwargs)
            except Exception:
                logger.exception("edi_data_plane_single_send_failed", queue_name=queue_name)
                raise

        if self._sqs_client:
            await _do_publish(self._sqs_client)
        else:
            async with self.session.client(
                "sqs", endpoint_url=self.endpoint_url, region_name=self.region
            ) as sqs:
                await _do_publish(sqs)
