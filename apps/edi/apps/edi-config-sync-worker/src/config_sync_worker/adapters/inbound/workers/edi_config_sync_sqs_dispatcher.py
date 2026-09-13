from typing import Any

import structlog
from edi.domain.events import ProvisioningEvent
from pydantic import TypeAdapter, ValidationError
from seedwork.events import EventEnvelope

from config_sync_worker.application.service import ProvisioningWorkerService
from config_sync_worker.domain.errors import PermanentProvisioningError
from config_sync_worker.ports.outbound.event_translator_port import EventTranslatorPort

logger = structlog.get_logger(__name__)

# The `source` field in EventEnvelope set by the UCP outbox repository.
# Used to discriminate cross-boundary (UCP → EDI) events from internal EDI events.
_UCP_SOURCE = "soopa.ucp"


class EdiConfigSyncSqsDispatcher:
    def __init__(
        self,
        domain_service: ProvisioningWorkerService,
        translator_port: EventTranslatorPort,
    ):
        self.domain_service = domain_service
        self.translator_port = translator_port
        self._envelope_adapter: TypeAdapter[EventEnvelope] = TypeAdapter(EventEnvelope)
        self._event_adapter: TypeAdapter[ProvisioningEvent] = TypeAdapter(ProvisioningEvent)

    async def dispatch_raw(self, body: dict[str, Any]) -> None:
        """
        Parses an SQS/SNS payload and dispatches it to the domain service.

        All messages on the provisioning queue are standard EventEnvelopes published
        by bounded-context outbox relays. The `source` field discriminates the origin:

          - source == "soopa.ucp"  → cross-boundary UCP event; must pass through
                                     the ACL translator before domain dispatch.
          - any other source       → internal EDI ProvisioningEvent; the payload
                                     already contains `event_type` and `resource_id`
                                     in the EDI domain schema.
        """
        bound_logger = logger.bind(payload_keys=list(body.keys()))
        bound_logger.info("sqs_dispatcher_invoked")

        # Step 1: Parse the outer EventEnvelope — this is always present regardless of source.
        try:
            envelope = self._envelope_adapter.validate_python(body)
        except ValidationError as e:
            bound_logger.exception("sqs_dispatcher_envelope_parse_failed")
            raise PermanentProvisioningError(f"Message is not a valid EventEnvelope: {e}") from e

        bound_logger = bound_logger.bind(
            event_type=envelope.event_type,
            source=envelope.source,
            tenant_id=envelope.tenant_id,
            event_id=envelope.id,
        )

        # Step 2: Route based on origin source.
        if envelope.source == _UCP_SOURCE:
            # Cross-boundary event — must be translated by the ACL before dispatch.
            bound_logger.info("sqs_dispatcher_routing_to_acl_translator")
            try:
                translated = self.translator_port.translate_external_event(
                    envelope.event_type, body
                )
            except ValueError as e:
                bound_logger.exception(
                    "sqs_dispatcher_acl_translation_failed",
                    action="dlq",
                )
                raise PermanentProvisioningError(
                    f"Malformed UCP event {envelope.event_type}: {e}"
                ) from e

            if translated is None:
                bound_logger.info(
                    "sqs_dispatcher_unregistered_ucp_event",
                    action="drop",
                )
                return

            try:
                parsed_event = self._event_adapter.validate_python(translated)
            except ValidationError as e:
                bound_logger.exception("sqs_dispatcher_translated_event_parse_failed")
                raise PermanentProvisioningError(
                    f"Translated UCP event failed ProvisioningEvent validation: {e}"
                ) from e

        else:
            # Internal EDI event — payload IS the ProvisioningEvent fields.
            bound_logger.info("sqs_dispatcher_routing_to_internal_handler")
            payload = envelope.payload
            event_dict = {
                "tenant_id": envelope.tenant_id,
                "event_type": envelope.event_type,
                "resource_id": payload.get("resource_id") if isinstance(payload, dict) else None,
            }
            try:
                parsed_event = self._event_adapter.validate_python(event_dict)
            except ValidationError as e:
                bound_logger.exception("sqs_dispatcher_internal_event_parse_failed")
                raise PermanentProvisioningError(
                    f"Internal EDI event {envelope.event_type} failed validation: {e}"
                ) from e

        # Step 3: Guard — resource_id is mandatory for all provisioning operations.
        if parsed_event.resource_id is None:
            raise PermanentProvisioningError(
                f"Event {parsed_event.event_type} missing required resource_id"
            )

        bound_logger.info(
            "sqs_message_dispatching",
            resource_id=parsed_event.resource_id,
        )

        await self.domain_service.process_event(parsed_event)

        bound_logger.info(
            "sqs_message_dispatched_successfully",
            resource_id=parsed_event.resource_id,
        )
