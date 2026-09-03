import uuid

import structlog
from seedwork.domain.types import JsonValue

from edi.domain.enums import EdiDirection, MessageStatus, PipelineEventType
from edi.ports.outbound.data_plane_unit_of_work_port import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class PipelineLifecycleUseCase:
    """
    Application Use Case — Saga Coordinator for the Pipeline Lifecycle.

    Listens to domain events (TRANSFORM_COMPLETED, DELIVERY_COMPLETED) and
    coordinates state transitions across the layers (EdiMessage, EdiJson, ApiGateway)
    to ensure strict SRP in the workers.
    """

    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def handle_transform_completed(self, payload: dict[str, JsonValue]) -> None:
        """
        Triggered when a TransformUseCase finishes transforming a payload.
        """
        trace_id = str(payload["trace_id"])
        direction_val = payload.get("direction")
        direction = str(direction_val) if direction_val is not None else EdiDirection.INBOUND.value
        logger.info(
            "pipeline_lifecycle.transform_completed",
            trace_id=trace_id,
        )

        async with self.uow:
            if direction == EdiDirection.INBOUND.value:
                gs_sender_val = payload.get("gs_sender_id")
                gs_receiver_val = payload.get("gs_receiver_id")
                txn_val = payload.get("transaction_type")

                gs_sender_id = str(gs_sender_val) if gs_sender_val else None
                gs_receiver_id = str(gs_receiver_val) if gs_receiver_val else None
                transaction_type = str(txn_val) if txn_val else None

                if gs_sender_id and gs_receiver_id:
                    await self.uow.repository.update_edi_message_metadata(
                        trace_id=trace_id,
                        gs_sender_id=gs_sender_id,
                        gs_receiver_id=gs_receiver_id,
                        transaction_type=transaction_type,
                    )
                await self.uow.repository.update_edi_message_status(
                    trace_id, str(MessageStatus.TRANSFORMED)
                )
            else:
                trading_partner_id = (
                    str(payload.get("trading_partner_id"))
                    if payload.get("trading_partner_id")
                    else None
                )

                update_kwargs: dict[str, str] = {}
                if trading_partner_id:
                    update_kwargs["trading_partner_id"] = trading_partner_id
                if "standard" in payload and payload["standard"] is not None:
                    update_kwargs["standard"] = str(payload["standard"])
                if "isa_sender_id" in payload and payload["isa_sender_id"] is not None:
                    update_kwargs["sender_id"] = str(payload["isa_sender_id"])
                if "isa_receiver_id" in payload and payload["isa_receiver_id"] is not None:
                    update_kwargs["receiver_id"] = str(payload["isa_receiver_id"])
                if "gs_sender_id" in payload and payload["gs_sender_id"] is not None:
                    update_kwargs["gs_sender_id"] = str(payload["gs_sender_id"])
                if "gs_receiver_id" in payload and payload["gs_receiver_id"] is not None:
                    update_kwargs["gs_receiver_id"] = str(payload["gs_receiver_id"])

                if update_kwargs:
                    await self.uow.repository.update_edi_json(trace_id=trace_id, **update_kwargs)

                await self.uow.repository.update_edi_json_status(
                    trace_id, str(MessageStatus.TRANSFORMED)
                )

            # Emit DELIVER command
            deliver_idempotency_key = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{trace_id}:DELIVER"))
            await self.uow.outbox.append_event(
                idempotency_key=deliver_idempotency_key,
                event_type=PipelineEventType.DELIVER_EVENT,
                payload={"trace_id": trace_id},
            )
            await self.uow.commit()

        logger.info("pipeline_lifecycle.deliver_event_triggered", trace_id=trace_id)

    async def handle_delivery_completed(self, payload: dict[str, JsonValue]) -> None:
        """
        Triggered when a DeliveryUseCase completes its delivery attempt.
        """
        trace_id = str(payload["trace_id"])
        direction = str(payload.get("direction", EdiDirection.INBOUND.value))
        status = payload.get("status")

        # Validate status field is present before proceeding
        if not status:
            logger.error(
                "pipeline_lifecycle.missing_status",
                trace_id=trace_id,
                payload=payload,
            )
            raise ValueError(
                f"Missing status field in DELIVERY_COMPLETED payload for trace_id={trace_id}"
            )

        logger.info(
            "pipeline_lifecycle.delivery_completed",
            status=status,
            trace_id=trace_id,
        )

        async with self.uow:
            if direction == EdiDirection.INBOUND.value:
                await self.uow.repository.update_api_payload_status(trace_id, str(status))
            else:
                await self.uow.repository.update_edi_message_status(trace_id, str(status))
            await self.uow.commit()
