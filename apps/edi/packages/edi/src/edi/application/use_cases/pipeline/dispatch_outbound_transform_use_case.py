import dataclasses
from typing import cast

import structlog
from seedwork.domain.types import JsonDict
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_deterministic_id

from edi.config.settings import AppSettings
from edi.core.pipeline.connection_type_resolver import ConnectionTypeResolver
from edi.core.pipeline.transaction_type_resolver import TransactionTypeResolver
from edi.domain.constants import WILDCARD_TRANSACTION_TYPE
from edi.domain.enums import (
    ConnectionType,
    EdiDirection,
    EdiStandard,
    MessageStatus,
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
from edi.domain.types import AstNode
from edi.ports.outbound.transaction_repository import CreateEdiMessageCommand
from edi.ports.outbound.transformer_port import TransformerPort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class DispatchOutboundTransformUseCase:
    """
    Application Use Case for orchestrating outbound JSON to EDI transformation.
    """

    def __init__(
        self,
        uow: DataPlaneUnitOfWorkPort,
        transformer: TransformerPort,
        settings: AppSettings,
    ) -> None:
        self.uow = uow
        self.transformer = transformer
        self._settings = settings

    async def _resolve_route_config(
        self, edi_json: EdiJsonDomainModel, trace_id: str
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

        route_config = await self.uow.edi_headers.get_outbound_edi_header_by_trading_partner_id(
            trading_partner_id=trading_partner_id, tenant_id=tenant_id
        )
        outbound_route = await self.uow.outbound_routes.get_outbound_route_by_trading_partner_id(
            trading_partner_id=trading_partner_id, tenant_id=tenant_id
        )

        if not route_config or not outbound_route:
            raise OutboundRouteNotFoundError(
                trading_partner_id=trading_partner_id,
                tenant_id=tenant_id,
            )

        return trading_partner_id, route_config, outbound_route

    async def _offload_to_compute_queue(
        self,
        trace_id: str,
        tenant_id: str,
        standard: str,
        transaction_type: str,
        route_config: JsonDict,
    ) -> None:
        logger.info(
            "outbound_transform.offloaded_to_compute_queue",
            trace_id=trace_id,
        )
        compute_key = generate_deterministic_id(
            SystemIdPrefix.IDEMPOTENCY, trace_id, "COMPUTE_TRANSFORMATION_COMMAND"
        )
        await self.uow.outbox.append_event(
            idempotency_key=compute_key,
            event_type=PipelineEventType.COMPUTE_TRANSFORMATION_COMMAND.value,
            payload={
                "trace_id": trace_id,
                "tenant_id": tenant_id,
                "direction": EdiDirection.OUTBOUND.value,
                "standard": standard,
                "transaction_type": transaction_type,
                "route_config": route_config,
            },
        )

    # Extraction logic lives exclusively in TransactionTypeResolver (DRY).

    async def execute(self, trace_id: str) -> None:
        """Transforms an outbound JSON payload to X12 EDI."""
        logger.info("outbound_transform.started", trace_id=trace_id)

        async with self.uow:
            edi_json = await self.uow.transactions.get_edi_json(trace_id)
            if not edi_json:
                raise TransactionNotFoundError(trace_id)

            json_payload = edi_json.payload
            if not json_payload or not (
                isinstance(json_payload, dict)
                or (
                    isinstance(json_payload, list)
                    and all(isinstance(node, dict) for node in json_payload)
                )
            ):
                raise TransactionNotFoundError(trace_id)

            (
                trading_partner_id,
                route_config_dto,
                outbound_route_dto,
            ) = await self._resolve_route_config(edi_json, trace_id)

            route_config = dataclasses.asdict(route_config_dto)
            outbound_route = dataclasses.asdict(outbound_route_dto)

            raw_standard = route_config.get("default_standard")
            standard = str(raw_standard) if raw_standard is not None else EdiStandard.X12.value

            isa_sender_id = str(route_config.get("isa_sender_id") or "")
            isa_receiver_id = str(route_config.get("isa_receiver_id") or "")

            gs_sender_id_raw = route_config.get("gs_sender_id")
            gs_sender_id = str(gs_sender_id_raw) if gs_sender_id_raw is not None else None

            gs_receiver_id_raw = route_config.get("gs_receiver_id")
            gs_receiver_id = str(gs_receiver_id_raw) if gs_receiver_id_raw is not None else None
            route_txn_type = route_config.get("transaction_type")
            if route_txn_type == WILDCARD_TRANSACTION_TYPE:
                route_txn_type = None

            # Resolve transaction_type via a strict, ordered fallback chain:
            #   Tier 1 — Route config value (explicit, non-wildcard)
            #   Tier 2 — Stored transaction_type on the EdiJson record
            #   Tier 3 — Dynamic extraction from raw payload (shared domain service)
            # A hard domain error is raised if all tiers are exhausted — UNKNOWN is
            # never a valid fallback because it causes grammar engine import failures.
            explicit_txn_type = route_txn_type or edi_json.transaction_type

            transaction_type = TransactionTypeResolver.resolve(
                explicit_type=explicit_txn_type,
                payload=edi_json.payload,
            )

            if not transaction_type:
                raise UnresolvableTransactionTypeError(trace_id)

            # Structured observability: emit a warning when we had to fall back to
            # dynamic payload extraction so ops teams can identify under-configured routes.
            if not route_txn_type and not edi_json.transaction_type:
                logger.warning(
                    "outbound_transform.transaction_type_inferred_from_payload",
                    trace_id=trace_id,
                    resolved_type=transaction_type,
                    trading_partner_id=trading_partner_id,
                )

            route_config["transaction_type"] = transaction_type

            if "environment" not in route_config:
                route_config["environment"] = self._settings.edi_environment

            connection_type = ConnectionTypeResolver.resolve(route_config, outbound_route)
            route_config["connection_type"] = connection_type.value

            if self._settings.enable_heavy_compute_queue:
                await self._offload_to_compute_queue(
                    trace_id, edi_json.tenant_id or "", standard, transaction_type, route_config
                )
                await self.uow.commit()
                return

            raw_edi_bytes = await self.transformer.transform_json_to_edi(
                payload=cast(AstNode | list[AstNode], json_payload),
                standard=standard,
                transaction_type=transaction_type,
                route_config=route_config,
            )

            edi_str = raw_edi_bytes.decode("utf-8")

            await self.uow.transactions.create_edi_message(
                command=CreateEdiMessageCommand(
                    trace_id=trace_id,
                    tenant_id=edi_json.tenant_id or "",
                    direction=EdiDirection.OUTBOUND,
                    edi_data=edi_str,
                    format_standard=standard,
                    transaction_type=transaction_type,
                    status=MessageStatus.PENDING_DELIVERY,
                    connection_type=ConnectionType(connection_type.value),
                    sender_id=isa_sender_id,
                    receiver_id=isa_receiver_id,
                    gs_sender_id=gs_sender_id,
                    gs_receiver_id=gs_receiver_id,
                    trading_partner_id=trading_partner_id,
                    is_replay=edi_json.is_replay,
                    parent_trace_id=edi_json.parent_trace_id,
                    original_trace_id=edi_json.original_trace_id,
                )
            )

            transform_completed_key = generate_deterministic_id(
                SystemIdPrefix.IDEMPOTENCY, trace_id, "TRANSFORMATION_COMPLETED"
            )
            await self.uow.outbox.append_event(
                idempotency_key=transform_completed_key,
                event_type=PipelineEventType.TRANSFORMATION_COMPLETED.value,
                payload={
                    "trace_id": trace_id,
                    "direction": EdiDirection.OUTBOUND.value,
                    "trading_partner_id": trading_partner_id,
                    "standard": standard,
                    "isa_sender_id": isa_sender_id,
                    "isa_receiver_id": isa_receiver_id,
                    "gs_sender_id": gs_sender_id,
                    "gs_receiver_id": gs_receiver_id,
                },
            )

            await self.uow.commit()

        logger.info("outbound_transform.completed", trace_id=trace_id)
