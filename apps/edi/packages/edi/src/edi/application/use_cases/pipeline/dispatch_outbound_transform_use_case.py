import dataclasses
import uuid
from typing import cast

import structlog
from seedwork.domain.types import JsonValue

from edi.application.dtos.routes import OutboundEdiHeaderDTO, OutboundRouteDTO
from edi.config.settings import AppSettings
from edi.domain.enums import EdiDirection, EdiStandard, MessageStatus, PipelineEventType
from edi.domain.models.transactions import EdiJsonDomainModel
from edi.domain.types import AstNode
from edi.ports.outbound.data_plane_unit_of_work_port import DataPlaneUnitOfWorkPort
from edi.ports.outbound.transformer_port import TransformerPort

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
    ) -> tuple[str, OutboundEdiHeaderDTO, OutboundRouteDTO]:
        trading_partner_id = edi_json.trading_partner_id
        tenant_id = edi_json.tenant_id

        business_metadata = edi_json.business_metadata or {}
        routing_meta = business_metadata.get("_routing")
        if isinstance(routing_meta, dict) and not trading_partner_id:
            tp_id = routing_meta.get("trading_partner_id")
            trading_partner_id = str(tp_id) if tp_id else None

        if not trading_partner_id:
            raise ValueError(
                f"Missing payload/routing metadata (trading_partner_id) for trace_id={trace_id}"
            )

        if tenant_id is None:
            raise ValueError(f"Missing tenant_id for trace_id={trace_id}")

        route_config = await self.uow.repository.get_outbound_edi_header_by_route_or_partner(
            trading_partner_id=trading_partner_id, tenant_id=tenant_id
        )
        outbound_route = await self.uow.repository.get_outbound_route_by_trading_partner_id(
            trading_partner_id=trading_partner_id, tenant_id=tenant_id
        )

        if not route_config or not outbound_route:
            raise ValueError(f"Unsuccessful route/header lookup for trace_id={trace_id}")

        return trading_partner_id, route_config, outbound_route

    async def _offload_to_compute_queue(
        self,
        trace_id: str,
        standard: str,
        transaction_type: str,
        route_config: dict[str, JsonValue],
    ) -> None:
        logger.info(
            "outbound_transform.offloaded_to_compute_queue",
            trace_id=trace_id,
        )
        compute_key = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{trace_id}:COMPUTE_TRANSFORM_EVENT"))
        await self.uow.outbox.append_event(
            idempotency_key=compute_key,
            event_type=PipelineEventType.COMPUTE_TRANSFORM_EVENT.value,
            payload={
                "trace_id": trace_id,
                "direction": EdiDirection.OUTBOUND.value,
                "standard": standard,
                "transaction_type": transaction_type,
                "route_config": route_config,
            },
        )

    def _determine_connection_type(
        self, route_config: dict[str, JsonValue], outbound_route: dict[str, JsonValue]
    ) -> str:
        connection_type = route_config.get("connection_type", "UNKNOWN")
        if connection_type == "UNKNOWN" and outbound_route:
            if outbound_route.get("as2_partner_id"):
                return "AS2"
            if outbound_route.get("sftp_partner_id"):
                return "SFTP"
        return str(connection_type)

    async def execute(self, trace_id: str) -> None:
        """Transforms an outbound JSON payload to X12 EDI."""
        logger.info("outbound_transform.started", trace_id=trace_id)

        async with self.uow:
            edi_json = await self.uow.repository.get_edi_json(trace_id)
            if not edi_json:
                raise ValueError(f"No EdiJson record found for trace_id={trace_id}")

            json_payload = edi_json.payload
            if not json_payload or not (
                isinstance(json_payload, dict)
                or (
                    isinstance(json_payload, list)
                    and all(isinstance(node, dict) for node in json_payload)
                )
            ):
                raise ValueError(f"Payload is missing for trace_id={trace_id}")

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
            if route_txn_type == "*":
                route_txn_type = None

            transaction_type = route_txn_type or edi_json.transaction_type or "UNKNOWN"
            route_config["transaction_type"] = transaction_type

            if "environment" not in route_config:
                route_config["environment"] = self._settings.edi_environment

            if self._settings.enable_heavy_compute_queue:
                await self._offload_to_compute_queue(
                    trace_id, standard, transaction_type, route_config
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
            connection_type = self._determine_connection_type(route_config, outbound_route)

            await self.uow.repository.save_edi_message(
                trace_id=trace_id,
                direction=EdiDirection.OUTBOUND.value,
                edi_data=edi_str,
                format_standard=standard,
                transaction_type=transaction_type,
                status=MessageStatus.PENDING_DELIVERY.value,
                connection_type=connection_type,
                sender_id=isa_sender_id,
                receiver_id=isa_receiver_id,
                gs_sender_id=gs_sender_id,
                gs_receiver_id=gs_receiver_id,
                trading_partner_id=trading_partner_id,
                tenant_id=edi_json.tenant_id,
            )

            transform_completed_key = str(
                uuid.uuid5(uuid.NAMESPACE_OID, f"{trace_id}:TRANSFORM_COMPLETED")
            )
            await self.uow.outbox.append_event(
                idempotency_key=transform_completed_key,
                event_type=PipelineEventType.TRANSFORM_COMPLETED.value,
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
