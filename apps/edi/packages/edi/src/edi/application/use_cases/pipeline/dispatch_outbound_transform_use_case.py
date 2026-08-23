import uuid
from typing import Any

import structlog
from edi.config.settings import AppSettings
from edi.domain.direction import MessageDirection
from edi.domain.events import PipelineEventType
from edi.domain.status import MessageStatus

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
        self, edi_json: Any, trace_id: str
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        trading_partner_id = edi_json.trading_partner_id
        tenant_id = edi_json.tenant_id

        business_metadata = edi_json.business_metadata or {}
        routing_meta = business_metadata.get("_routing") or {}

        if not trading_partner_id:
            trading_partner_id = routing_meta.get("trading_partner_id")

        if not trading_partner_id:
            raise ValueError(
                f"Missing payload/routing metadata (trading_partner_id) for trace_id={trace_id}"
            )

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
        self, trace_id: str, standard: str, transaction_type: str, route_config: dict[str, Any]
    ) -> None:
        logger.info(
            "outbound_transform.offloaded_to_compute_queue",
            trace_id=trace_id,
        )
        compute_key = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{trace_id}:COMPUTE_TRANSFORM_EVENT"))
        await self.uow.outbox.append_event(
            idempotency_key=compute_key,
            event_type=PipelineEventType.COMPUTE_TRANSFORM_EVENT,
            payload={
                "trace_id": trace_id,
                "direction": MessageDirection.OUTBOUND,
                "standard": standard,
                "transaction_type": transaction_type,
                "route_config": route_config,
            },
        )

    def _determine_connection_type(
        self, route_config: dict[str, Any], outbound_route: dict[str, Any]
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
            if not json_payload:
                raise ValueError(f"Payload is missing for trace_id={trace_id}")

            trading_partner_id, route_config, outbound_route = await self._resolve_route_config(
                edi_json, trace_id
            )

            standard = route_config.get("default_standard", "X12")
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
                payload=json_payload,
                standard=standard,
                transaction_type=transaction_type,
                route_config=route_config,
            )

            edi_str = raw_edi_bytes.decode("utf-8")
            connection_type = self._determine_connection_type(route_config, outbound_route)

            await self.uow.repository.save_edi_message(
                trace_id=trace_id,
                direction=MessageDirection.OUTBOUND,
                edi_data=edi_str,
                format_standard=standard,
                transaction_type=transaction_type,
                status=MessageStatus.PENDING_DELIVERY,
                connection_type=connection_type,
                sender_id=route_config.get("isa_sender_id"),
                receiver_id=route_config.get("isa_receiver_id"),
                gs_sender_id=route_config.get("gs_sender_id"),
                gs_receiver_id=route_config.get("gs_receiver_id"),
                trading_partner_id=trading_partner_id,
                tenant_id=edi_json.tenant_id,
            )

            transform_completed_key = str(
                uuid.uuid5(uuid.NAMESPACE_OID, f"{trace_id}:TRANSFORM_COMPLETED")
            )
            await self.uow.outbox.append_event(
                idempotency_key=transform_completed_key,
                event_type=PipelineEventType.TRANSFORM_COMPLETED,
                payload={
                    "trace_id": trace_id,
                    "direction": MessageDirection.OUTBOUND,
                    "trading_partner_id": trading_partner_id,
                    "standard": standard,
                    "isa_sender_id": route_config.get("isa_sender_id"),
                    "isa_receiver_id": route_config.get("isa_receiver_id"),
                    "gs_sender_id": route_config.get("gs_sender_id"),
                    "gs_receiver_id": route_config.get("gs_receiver_id"),
                },
            )

            await self.uow.commit()

        logger.info("outbound_transform.completed", trace_id=trace_id)
