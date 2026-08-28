from typing import Any

import structlog
from edi.domain.events import ProvisioningEvent
from pydantic import TypeAdapter, ValidationError

from config_sync_worker.domain.errors import PermanentProvisioningError
from config_sync_worker.ports.outbound.event_translator_port import EventTranslatorPort

logger = structlog.get_logger(__name__)


class EdiConfigSyncSqsDispatcher:
    def __init__(
        self,
        domain_service: Any,
        translator_port: EventTranslatorPort,
    ):
        self.domain_service = domain_service
        self.translator_port = translator_port
        self._event_adapter: TypeAdapter[ProvisioningEvent] = TypeAdapter(ProvisioningEvent)

    async def dispatch_raw(self, body: dict[str, Any]) -> None:
        """Parses the SQS/SNS payload, translates, and invokes domain logic."""
        external_event_type = body.get("eventType")
        if external_event_type:
            try:
                translated_body = self.translator_port.translate_external_event(
                    external_event_type, body
                )
                if translated_body is None:
                    logger.info(
                        "unregistered_external_event_type",
                        external_event_type=external_event_type,
                        action="drop",
                    )
                    return
                body = translated_body
            except ValueError as e:
                logger.exception(
                    "permanent_validation_error",
                    external_event_type=external_event_type,
                    action="dlq",
                )
                raise PermanentProvisioningError(
                    f"Malformed external event {external_event_type}: {e}"
                ) from e

        # Extract envelope properties mapping to internal schema
        try:
            event_dict = {
                "tenant_id": body.get("tenant_id"),
                "event_type": body.get("eventType", body.get("event_type", "unknown")),
                "resource_id": body.get("resource_id") or body.get("id"),
            }
            parsed_event = self._event_adapter.validate_python(event_dict)
        except ValidationError as e:
            logger.exception(
                "provisioning_event_validation_error",
                event_type=body.get("eventType", body.get("event_type", "unknown")),
            )
            raise PermanentProvisioningError(f"Invalid provision event payload: {e}") from e

        if parsed_event.resource_id is None:
            raise PermanentProvisioningError(
                f"Event {parsed_event.event_type} missing required resource_id"
            )

        logger.info(
            "sqs_message_received",
            event_type=parsed_event.event_type,
            resource_id=parsed_event.resource_id,
            tenant_id=parsed_event.tenant_id,
        )

        await self.domain_service.process_event(parsed_event)
