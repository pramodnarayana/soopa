import logging
from typing import Any

from domain.direction import MessageDirection
from domain.events import PipelineEventType
from domain.status import MessageStatus

from pipeline.ports.repository import RepositoryPort

logger = logging.getLogger(__name__)


class TraceLifecycleService:
    """
    Saga Coordinator for the Trace Lifecycle.
    Listens to domain events and coordinates state transitions across the layers
    (EdiMessage, EdiJson, ApiGateway) to ensure strict SRP in the workers.
    """

    def __init__(self, repository: RepositoryPort) -> None:
        self.repository = repository

    async def handle_transform_completed(self, payload: dict[str, Any]) -> None:
        """
        Triggered when TransformService finishes transforming a payload.
        """
        trace_id = payload["trace_id"]
        direction = payload.get("direction", MessageDirection.INBOUND)
        logger.info(f"TraceLifecycle: handling TRANSFORM_COMPLETED for trace_id={trace_id}")

        if direction == MessageDirection.INBOUND:
            # Update the parent EdiMessage with the extracted metadata
            gs_sender_id = payload.get("gs_sender_id")
            gs_receiver_id = payload.get("gs_receiver_id")
            transaction_type = payload.get("transaction_type")

            if gs_sender_id and gs_receiver_id:
                await self.repository.update_edi_message_metadata(
                    trace_id=trace_id,
                    gs_sender_id=gs_sender_id,
                    gs_receiver_id=gs_receiver_id,
                    transaction_type=transaction_type,
                )
            await self.repository.update_edi_message_status(
                trace_id, str(MessageStatus.TRANSFORMED)
            )
        else:
            # For OUTBOUND, the input is EdiJson. Its terminal state is TRANSFORMED.
            import uuid

            trading_partner_id = payload.get("trading_partner_id")

            # Pack update kwargs (omitting None values if not present)
            update_kwargs = {}
            if trading_partner_id:
                update_kwargs["trading_partner_id"] = trading_partner_id
            if "standard" in payload:
                update_kwargs["standard"] = payload["standard"]
            if "isa_sender_id" in payload:
                update_kwargs["sender_id"] = payload["isa_sender_id"]
            if "isa_receiver_id" in payload:
                update_kwargs["receiver_id"] = payload["isa_receiver_id"]
            if "gs_sender_id" in payload:
                update_kwargs["gs_sender_id"] = payload["gs_sender_id"]
            if "gs_receiver_id" in payload:
                update_kwargs["gs_receiver_id"] = payload["gs_receiver_id"]

            if update_kwargs:
                await self.repository.update_edi_json(trace_id=trace_id, **update_kwargs)

            await self.repository.update_edi_json_status(trace_id, MessageStatus.TRANSFORMED)

        # Emit DELIVER command
        import uuid

        deliver_idempotency_key = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{trace_id}:DELIVER"))
        await self.repository.publish_outbox_event(
            idempotency_key=deliver_idempotency_key,
            event_type=PipelineEventType.DELIVER_EVENT,
            payload={"trace_id": trace_id},
        )
        logger.info(f"TraceLifecycle: Triggered DELIVER_EVENT for trace_id={trace_id}")

    async def handle_delivery_completed(self, payload: dict[str, Any]) -> None:
        """
        Triggered when DeliveryService completes its delivery attempt.
        """
        trace_id = payload["trace_id"]
        direction = payload.get("direction", MessageDirection.INBOUND)
        status = payload.get("status")
        logger.info(
            f"TraceLifecycle: handling DELIVERY_COMPLETED ({status}) for trace_id={trace_id}"
        )

        if direction == MessageDirection.INBOUND:
            await self.repository.update_api_payload_status(trace_id, str(status))
            # We do NOT update edi_message or edi_json for inbound delivery.
        else:
            await self.repository.update_edi_message_status(trace_id, str(status))
            # We do NOT update edi_json or api_gateway for outbound delivery.
