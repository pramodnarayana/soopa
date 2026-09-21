import dataclasses
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import structlog
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.id_registry import DomainIdPrefix, SystemIdPrefix
from seedwork.utils import generate_deterministic_id, generate_id

from edi.config.settings import AppSettings
from edi.core.pipeline.connection_type_resolver import ConnectionTypeResolver
from edi.core.pipeline.transaction_type_resolver import TransactionTypeResolver
from edi.domain.constants import WILDCARD_TRANSACTION_TYPE
from edi.domain.enums import (
    EdiDirection,
    EdiStandard,
    PipelineEventType,
)
from edi.domain.events import TransformSuccessful
from edi.domain.exceptions import (
    OutboundRouteNotFoundError,
    TransactionNotFoundError,
    UnresolvableTransactionTypeError,
)
from edi.domain.models.headers import OutboundEdiHeaderDomainModel
from edi.domain.models.outbound_routes import OutboundRouteDomainModel
from edi.domain.models.transactions import EdiJsonDomainModel, EdiMessageDomainModel
from edi.domain.types import AstNode
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
        settings: AppSettings,
    ) -> None:
        self.uow_factory = uow_factory
        self.transformer = transformer
        self._settings = settings

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

        route_config = await uow.edi_headers.get_outbound_edi_header_by_trading_partner_id(
            trading_partner_id=trading_partner_id, tenant_id=tenant_id
        )
        outbound_route = await uow.outbound_routes.get_outbound_route_by_trading_partner_id(
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
        uow: DataPlaneUnitOfWorkPort,
        idempotency_key: str | None = None,
    ) -> None:
        logger.info(
            "outbound_transform.offloaded_to_compute_queue",
            trace_id=trace_id,
        )
        if not idempotency_key:
            raise ValueError("idempotency_key is required for strict event chaining")

        compute_key = generate_deterministic_id(
            SystemIdPrefix.IDEMPOTENCY, idempotency_key, "COMPUTE_TRANSFORMATION_COMMAND"
        )
        await uow.outbox.append_event(
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

    def _resolve_transaction_type(
        self,
        route_config: JsonDict,
        edi_json: EdiJsonDomainModel,
        trace_id: str,
        trading_partner_id: str,
    ) -> str:
        route_txn_type_raw = route_config.get("transaction_type")
        route_txn_type = str(route_txn_type_raw) if route_txn_type_raw else None
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

    async def _save_edi_message(
        self,
        uow: DataPlaneUnitOfWorkPort,
        edi_json: EdiJsonDomainModel,
        trace_id: str,
        edi_str: str,
        standard: str,
        transaction_type: str,
        connection_type: str,
        route_config: JsonDict,
        trading_partner_id: str | None,
    ) -> EdiMessageDomainModel:
        isa_sender_id = str(route_config.get("isa_sender_id") or "")
        isa_receiver_id = str(route_config.get("isa_receiver_id") or "")
        gs_sender_id_raw = route_config.get("gs_sender_id")
        gs_sender_id = str(gs_sender_id_raw) if gs_sender_id_raw is not None else None
        gs_receiver_id_raw = route_config.get("gs_receiver_id")
        gs_receiver_id = str(gs_receiver_id_raw) if gs_receiver_id_raw is not None else None

        edi_msg = await uow.transactions.get_edi_message(trace_id)
        if edi_msg:
            edi_msg.mark_outbound_pending_delivery(
                edi_data=edi_str,
                format_standard=standard,
                transaction_type=transaction_type,
                connection_type=connection_type,
                sender_id=isa_sender_id,
                receiver_id=isa_receiver_id,
                gs_sender_id=gs_sender_id,
                gs_receiver_id=gs_receiver_id,
                trading_partner_id=trading_partner_id,
            )
        else:
            edi_msg = EdiMessageDomainModel.create_outbound(
                id=generate_id(DomainIdPrefix.EDI_MESSAGE.value),
                trace_id=trace_id,
                tenant_id=edi_json.tenant_id or "",
                replay_count=edi_json.replay_count,
                parent_trace_id=edi_json.parent_trace_id,
                original_trace_id=edi_json.original_trace_id,
                edi_data=edi_str,
                format_standard=standard,
                transaction_type=transaction_type,
                connection_type=connection_type,
                sender_id=isa_sender_id,
                receiver_id=isa_receiver_id,
                gs_sender_id=gs_sender_id,
                gs_receiver_id=gs_receiver_id,
                trading_partner_id=trading_partner_id,
            )
        return edi_msg

    def _validate_payload_exists(self, json_payload: JsonValue | None, trace_id: str) -> None:
        if not json_payload or not (
            isinstance(json_payload, dict)
            or (
                isinstance(json_payload, list)
                and all(isinstance(node, dict) for node in json_payload)
            )
        ):
            raise TransactionNotFoundError(trace_id)

    def _prepare_payload(self, json_payload: JsonValue | None) -> AstNode | list[AstNode]:
        if isinstance(json_payload, dict):
            return json_payload
        if isinstance(json_payload, list):
            if not all(isinstance(x, dict) for x in json_payload):
                raise TypeError("If payload is a list, all items must be dictionaries.")
            return [x for x in json_payload if isinstance(x, dict)]
        raise TypeError(
            f"Expected json_payload to be dict or list, got {type(json_payload).__name__}"
        )

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
                route_config_dto,
                outbound_route_dto,
            ) = await self._resolve_route_config(edi_json, trace_id, uow=uow)

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
            transaction_type = self._resolve_transaction_type(
                route_config=route_config,
                edi_json=edi_json,
                trace_id=trace_id,
                trading_partner_id=trading_partner_id,
            )
            route_config["transaction_type"] = transaction_type

            if "environment" not in route_config:
                route_config["environment"] = self._settings.edi_environment

            connection_type = ConnectionTypeResolver.resolve(route_config, outbound_route)
            route_config["connection_type"] = connection_type.value

            if self._settings.enable_heavy_compute_queue:
                await self._offload_to_compute_queue(
                    trace_id,
                    edi_json.tenant_id or "",
                    standard,
                    transaction_type,
                    route_config,
                    uow,
                    idempotency_key,
                )
                await uow.commit()
                return

            edi_payload = self._prepare_payload(json_payload)

            raw_edi_bytes = await self.transformer.transform_json_to_edi(
                payload=edi_payload,
                standard=standard,
                transaction_type=transaction_type,
                route_config=route_config,
            )

            edi_str = raw_edi_bytes.decode("utf-8")

            edi_msg = await self._save_edi_message(
                uow=uow,
                edi_json=edi_json,
                trace_id=trace_id,
                edi_str=edi_str,
                standard=standard,
                transaction_type=transaction_type,
                connection_type=connection_type.value,
                route_config=route_config,
                trading_partner_id=trading_partner_id,
            )

            if not idempotency_key:
                raise ValueError("idempotency_key is required for strict event chaining")

            transform_completed_key = generate_deterministic_id(
                SystemIdPrefix.IDEMPOTENCY, idempotency_key, "TRANSFORMATION_SUCCESSFUL"
            )

            edi_msg.add_domain_event(
                TransformSuccessful(
                    idempotency_key=transform_completed_key,
                    trace_id=trace_id,
                    tenant_id=edi_json.tenant_id or "",
                    direction=EdiDirection.OUTBOUND.value,
                    isa_sender_id=isa_sender_id,
                    isa_receiver_id=isa_receiver_id,
                    gs_sender_id=gs_sender_id,
                    gs_receiver_id=gs_receiver_id,
                    transaction_type=transaction_type,
                )
            )

            await uow.transactions.save(edi_msg)

            await uow.commit()

        logger.info("outbound_transform.completed", trace_id=trace_id)
