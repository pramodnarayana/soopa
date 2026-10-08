import typing
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import structlog
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from seedwork.domain.types import JsonValue
from seedwork.events import EventEnvelope
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_deterministic_id

from edi.core.pipeline.transaction_type_resolver import TransactionTypeResolver
from edi.domain.constants import WILDCARD_TRANSACTION_TYPE
from edi.domain.enums import (
    EdiDirection,
    EdiStandard,
    PipelineEventType,
)
from edi.domain.exceptions import (
    OutboundRouteNotFoundError,
    TransactionNotFoundError,
    UnresolvableTransactionTypeError,
)
from edi.domain.models.headers import OutboundEdiHeaderDomainModel
from edi.domain.models.outbound_routes import OutboundRouteDomainModel
from edi.domain.models.transactions import EdiJsonDomainModel
from edi.ports.outbound.transformer_port import TransformerPort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class DispatchOutboundTransformUseCase:
    """
    Application Use Case for orchestrating outbound JSON to EDI transformation.
    """

    def __init__(
        self,
        uow_factory: Callable[[], AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]],
        transformer: TransformerPort,
        settings: typing.Any,
        publisher: OutboxPublisherPort,
    ) -> None:
        self.uow_factory = uow_factory
        self.transformer = transformer
        self._settings = settings
        self.publisher = publisher

    async def _resolve_route_config(
        self, edi_json: EdiJsonDomainModel, trace_id: str, uow: DataPlaneUnitOfWorkPort
    ) -> tuple[str, OutboundEdiHeaderDomainModel, OutboundRouteDomainModel]:
        trading_partner_id = edi_json.trading_partner_id
        tenant_id = edi_json.tenant_id

        business_metadata = edi_json.business_metadata or {}
        routing_meta = business_metadata.get("_routing")
        if isinstance(routing_meta, dict) and not trading_partner_id:
            tp_id = routing_meta.get("trading_partner_id")
            trading_partner_id = str(tp_id) if tp_id else None

        if not trading_partner_id:
            raise TransactionNotFoundError(trace_id)

        if tenant_id is None:
            raise TransactionNotFoundError(trace_id)

        edi_headers = await uow.edi_headers.get_outbound_edi_header_by_trading_partner_id(
            trading_partner_id=trading_partner_id, tenant_id=tenant_id
        )
        outbound_route = await uow.outbound_routes.get_outbound_route_by_trading_partner_id(
            trading_partner_id=trading_partner_id, tenant_id=tenant_id
        )

        if not edi_headers or not outbound_route:
            raise OutboundRouteNotFoundError(
                trading_partner_id=trading_partner_id,
                tenant_id=tenant_id,
            )

        return trading_partner_id, edi_headers, outbound_route

    async def _offload_to_compute_queue(
        self,
        trace_id: str,
        tenant_id: str,
        standard: str,
        transaction_type: str,
        edi_headers: OutboundEdiHeaderDomainModel,
        uow: DataPlaneUnitOfWorkPort,
        trading_partner_id: str,
        idempotency_key: str | None = None,
    ) -> EventEnvelope:
        logger.info(
            "outbound_transform.offloaded_to_compute_queue",
            trace_id=trace_id,
        )
        if not idempotency_key:
            raise ValueError("idempotency_key is required for strict event chaining")

        compute_key = generate_deterministic_id(
            SystemIdPrefix.IDEMPOTENCY, idempotency_key, "COMPUTE_TRANSFORMATION_COMMAND"
        )
        if not edi_headers.gs_sender_id or not edi_headers.gs_sender_id.strip():
            raise ValueError(
                f"Mandatory GS Sender ID is missing for trading partner {trading_partner_id}"
            )
        if not edi_headers.gs_receiver_id or not edi_headers.gs_receiver_id.strip():
            raise ValueError(
                f"Mandatory GS Receiver ID is missing for trading partner {trading_partner_id}"
            )

        isa_usage = edi_headers.isa_usage_indicator or self._settings.edi_environment
        if not isa_usage or not isa_usage.strip():
            raise ValueError(
                f"Mandatory ISA Usage Indicator is missing for trading partner {trading_partner_id}"
            )

        return await uow.outbox.append_event(
            tenant_id=tenant_id,
            idempotency_key=compute_key,
            event_type=PipelineEventType.COMPUTE_TRANSFORMATION_COMMAND.value,
            payload={
                "trace_id": trace_id,
                "tenant_id": tenant_id,
                "direction": EdiDirection.OUTBOUND.value,
                "standard": standard,
                "transaction_type": transaction_type,
                "isa_sender_id": edi_headers.isa_sender_id,
                "isa_receiver_id": edi_headers.isa_receiver_id,
                "gs_sender_id": edi_headers.gs_sender_id,
                "gs_receiver_id": edi_headers.gs_receiver_id,
                "isa_usage_indicator": isa_usage,
            },
        )

    def _resolve_transaction_type(
        self,
        edi_headers: OutboundEdiHeaderDomainModel,
        edi_json: EdiJsonDomainModel,
        trace_id: str,
        trading_partner_id: str,
    ) -> str:
        route_txn_type = edi_headers.transaction_type
        if route_txn_type == WILDCARD_TRANSACTION_TYPE:
            route_txn_type = None

        explicit_txn_type = route_txn_type or edi_json.transaction_type

        transaction_type = TransactionTypeResolver.resolve(
            explicit_type=explicit_txn_type,
            payload=edi_json.payload,
        )

        if not transaction_type:
            raise UnresolvableTransactionTypeError(trace_id)

        if not route_txn_type and not edi_json.transaction_type:
            logger.warning(
                "outbound_transform.transaction_type_inferred_from_payload",
                trace_id=trace_id,
                resolved_type=transaction_type,
                trading_partner_id=trading_partner_id,
            )
        return transaction_type

    def _validate_payload_exists(self, json_payload: JsonValue | None, trace_id: str) -> None:
        if not json_payload or not (
            isinstance(json_payload, dict)
            or (
                isinstance(json_payload, list)
                and all(isinstance(node, dict) for node in json_payload)
            )
        ):
            raise TransactionNotFoundError(trace_id)

    # Extraction logic lives exclusively in TransactionTypeResolver (DRY).
    async def execute(self, trace_id: str, idempotency_key: str | None = None) -> None:
        """Transforms an outbound JSON payload to X12 EDI."""
        logger.info("outbound_transform.started", trace_id=trace_id)

        async with self.uow_factory() as uow, uow:
            edi_json = await uow.transactions.get_edi_json(trace_id)
            if not edi_json:
                raise TransactionNotFoundError(trace_id)

            if idempotency_key:
                is_new = await uow.record_idempotency(edi_json.tenant_id, idempotency_key)
                if not is_new:
                    logger.info("outbound_transform.duplicate_skipped", trace_id=trace_id)
                    return

            json_payload = edi_json.payload
            self._validate_payload_exists(json_payload, trace_id)

            (
                trading_partner_id,
                edi_headers,
                _outbound_route,
            ) = await self._resolve_route_config(edi_json, trace_id, uow=uow)

            standard = edi_headers.default_standard or EdiStandard.X12.value
            transaction_type = self._resolve_transaction_type(
                edi_headers=edi_headers,
                edi_json=edi_json,
                trace_id=trace_id,
                trading_partner_id=trading_partner_id,
            )

            envelope = await self._offload_to_compute_queue(
                trace_id,
                edi_json.tenant_id or "",
                standard,
                transaction_type,
                edi_headers,
                uow,
                trading_partner_id,
                idempotency_key,
            )
            await uow.commit()

        try:
            await self.publisher.publish(envelope)
            async with self.uow_factory() as uow, uow:
                await uow.outbox.mark_completed(envelope.id)
                await uow.commit()
        except Exception as e:
            logger.exception("sync_dispatch_failed_falling_back_to_sweeper", error=str(e))
        logger.info("outbound_transform.completed", trace_id=trace_id)
