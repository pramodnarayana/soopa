from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import structlog
from seedwork.domain.types import JsonDict
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_deterministic_id

from edi.domain.enums import EdiDirection, MessageStatus, PipelineEventType
from edi.ports.outbound.transaction_repository import UpdateEdiJsonCommand
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class PipelineLifecycleUseCase:
    """
    Application Use Case — Saga Coordinator for the Pipeline Lifecycle.

    Listens to domain events (TRANSFORMATION_COMPLETED, DELIVERY_COMPLETED) and
    coordinates state transitions across the layers (EdiMessage, EdiJson, ApiGateway)
    to ensure strict SRP in the workers.
    """

    def __init__(
        self, uow_factory: Callable[[], AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]]
    ) -> None:
        self.uow_factory = uow_factory

    async def handle_transform_successful(
        self, tenant_id: str, idempotency_key: str | None, payload: JsonDict
    ) -> None:
        """
        Triggered when a TransformUseCase finishes successfully transforming a payload.
        """
        trace_id = str(payload["trace_id"])
        direction_val = payload.get("direction")
        direction = str(direction_val) if direction_val is not None else EdiDirection.INBOUND.value
        logger.info(
            "pipeline_lifecycle.transform_successful",
            trace_id=trace_id,
        )

        async with self.uow_factory() as uow, uow:
            if idempotency_key:
                is_new = await uow.record_idempotency(tenant_id, idempotency_key)
                if not is_new:
                    logger.info("pipeline_lifecycle.duplicate_skipped", trace_id=trace_id)
                    return

            if direction == EdiDirection.INBOUND.value:
                gs_sender_val = payload.get("gs_sender_id")
                gs_receiver_val = payload.get("gs_receiver_id")
                txn_val = payload.get("transaction_type")

                gs_sender_id = str(gs_sender_val) if gs_sender_val else None
                gs_receiver_id = str(gs_receiver_val) if gs_receiver_val else None
                transaction_type = str(txn_val) if txn_val else None

                if gs_sender_id and gs_receiver_id:
                    await uow.transactions.update_edi_message_metadata(
                        trace_id=trace_id,
                        gs_sender_id=gs_sender_id,
                        gs_receiver_id=gs_receiver_id,
                        transaction_type=transaction_type,
                    )
                await uow.transactions.update_edi_message_status(
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

                if update_kwargs:
                    await uow.transactions.update_edi_json(
                        command=UpdateEdiJsonCommand(
                            trace_id=trace_id,
                            trading_partner_id=update_kwargs.get("trading_partner_id"),
                            standard=update_kwargs.get("standard"),
                        )
                    )

                await uow.transactions.update_edi_json_status(
                    trace_id, str(MessageStatus.TRANSFORMED)
                )

            # Emit DELIVER command
            # We use the incoming event's idempotency key to seed the next step.
            # This is critical for Replays: the trace_id is constant, but the incoming event
            # has a fresh idempotency_key. By chaining them, we prevent the outbox from
            # silently dropping the Replay's delivery request as a duplicate!
            transform_event_key = payload.get("idempotency_key", trace_id)
            deliver_idempotency_key = generate_deterministic_id(
                SystemIdPrefix.IDEMPOTENCY, str(transform_event_key), "DELIVER"
            )
            await uow.outbox.append_event(
                idempotency_key=deliver_idempotency_key,
                event_type=PipelineEventType.DELIVERY_REQUESTED,
                payload={"trace_id": trace_id},
            )
            await uow.commit()

        logger.info("pipeline_lifecycle.deliver_event_triggered", trace_id=trace_id)

    async def handle_transform_failed(
        self, tenant_id: str, idempotency_key: str | None, payload: JsonDict
    ) -> None:
        """
        Triggered when a TransformUseCase fails fatally.
        """
        trace_id = str(payload["trace_id"])
        direction_val = payload.get("direction")
        direction = str(direction_val) if direction_val is not None else EdiDirection.INBOUND.value
        failure_reason = payload.get("failure_reason", "Unknown failure")

        logger.error(
            "pipeline_lifecycle.transform_failed",
            trace_id=trace_id,
            failure_reason=failure_reason,
        )

        async with self.uow_factory() as uow, uow:
            if idempotency_key:
                is_new = await uow.record_idempotency(tenant_id, idempotency_key)
                if not is_new:
                    logger.info("pipeline_lifecycle.duplicate_skipped", trace_id=trace_id)
                    return

            if direction == EdiDirection.INBOUND.value:
                await uow.transactions.update_edi_message_status(
                    trace_id, str(MessageStatus.FAILED)
                )
            else:
                await uow.transactions.update_edi_json_status(trace_id, str(MessageStatus.FAILED))
            await uow.commit()

    async def handle_delivery_successful(
        self, tenant_id: str, idempotency_key: str | None, payload: JsonDict
    ) -> None:
        """
        Triggered when a DeliveryUseCase completes its delivery attempt successfully.
        """
        trace_id = str(payload["trace_id"])
        direction_val = payload.get("direction")
        direction = str(direction_val) if direction_val is not None else EdiDirection.INBOUND.value

        logger.info(
            "pipeline_lifecycle.delivery_successful",
            trace_id=trace_id,
        )

        async with self.uow_factory() as uow, uow:
            if idempotency_key:
                is_new = await uow.record_idempotency(tenant_id, idempotency_key)
                if not is_new:
                    logger.info("pipeline_lifecycle.duplicate_skipped", trace_id=trace_id)
                    return

            if direction == EdiDirection.INBOUND.value:
                await uow.api_gateway_transactions.update_api_payload_status(
                    trace_id, str(MessageStatus.DELIVERED)
                )
            else:
                await uow.transactions.update_edi_message_status(
                    trace_id, str(MessageStatus.DELIVERED)
                )
            await uow.commit()

    async def handle_delivery_failed(
        self, tenant_id: str, idempotency_key: str | None, payload: JsonDict
    ) -> None:
        """
        Triggered when a DeliveryUseCase encounters a terminal delivery failure.
        """
        trace_id = str(payload["trace_id"])
        direction_val = payload.get("direction")
        direction = str(direction_val) if direction_val is not None else EdiDirection.INBOUND.value
        failure_reason = payload.get("failure_reason", "Unknown failure")

        logger.error(
            "pipeline_lifecycle.delivery_failed",
            trace_id=trace_id,
            failure_reason=failure_reason,
        )

        async with self.uow_factory() as uow, uow:
            if idempotency_key:
                is_new = await uow.record_idempotency(tenant_id, idempotency_key)
                if not is_new:
                    logger.info("pipeline_lifecycle.duplicate_skipped", trace_id=trace_id)
                    return

            if direction == EdiDirection.INBOUND.value:
                await uow.api_gateway_transactions.update_api_payload_status(
                    trace_id, str(MessageStatus.FAILED)
                )
            else:
                await uow.transactions.update_edi_message_status(
                    trace_id, str(MessageStatus.FAILED)
                )
            await uow.commit()
