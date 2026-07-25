import logging
import uuid

from config.settings import get_settings
from domain.direction import MessageDirection
from domain.events import PipelineEventType
from domain.status import MessageStatus

from pipeline.ports.repository import RepositoryPort
from pipeline.ports.transformer import TransformerPort

logger = logging.getLogger(__name__)


class OutboundTransformService:
    """
    Domain service for orchestrating outbound JSON to EDI transformation.
    """

    def __init__(
        self,
        transformer: TransformerPort,
        repository: RepositoryPort,
    ) -> None:
        self.transformer = transformer
        self.repository = repository

    async def transform(self, trace_id: str) -> None:
        """Transforms an outbound JSON payload to X12 EDI."""
        logger.info(f"Starting outbound transformation pipeline for trace_id={trace_id}")

        edi_json = await self.repository.get_edi_json(trace_id)
        if not edi_json:
            raise ValueError(f"No EdiJson record found for trace_id={trace_id}")

        trading_partner_id = edi_json.trading_partner_id
        tenant_id = edi_json.tenant_id

        business_metadata = edi_json.business_metadata or {}
        routing_meta = business_metadata.get("_routing") or {}
        # Prefer explicit trading_partner_id on the record; fall back to business_metadata routing hint
        if not trading_partner_id:
            trading_partner_id = routing_meta.get("trading_partner_id")

        route_config = None
        outbound_route = None
        if trading_partner_id:
            route_config = await self.repository.get_outbound_edi_header_by_route_or_partner(
                trading_partner_id=trading_partner_id, tenant_id=tenant_id
            )
            outbound_route = await self.repository.get_outbound_route_by_trading_partner_id(
                trading_partner_id=trading_partner_id, tenant_id=tenant_id
            )

        if not route_config or not outbound_route:
            raise ValueError(
                f"Outbound route/header configuration not found for trace_id={trace_id}"
            )

        json_payload = edi_json.payload
        if not json_payload:
            raise ValueError(f"Payload is missing for trace_id={trace_id}")

        standard = route_config.get("default_standard", "X12")
        route_txn_type = route_config.get("transaction_type")
        if route_txn_type == "*":
            route_txn_type = None

        transaction_type = route_txn_type or edi_json.transaction_type or "UNKNOWN"

        # Ensure the resolved transaction type is used by the envelope builders
        route_config["transaction_type"] = transaction_type

        settings = get_settings()

        # Ensure environment is present for the transformer
        if "environment" not in route_config:
            route_config["environment"] = settings.edi_environment

        if settings.enable_heavy_compute_queue:
            logger.info(
                f"Offloading heavy JSON-to-EDI formatting to compute queue for trace_id={trace_id}"
            )
            compute_key = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{trace_id}:COMPUTE_TRANSFORM_EVENT"))
            await self.repository.publish_outbox_event(
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
            return

        raw_edi_bytes = await self.transformer.transform_json_to_edi(
            payload=json_payload,
            standard=standard,
            transaction_type=transaction_type,
            route_config=route_config,
        )

        edi_str = raw_edi_bytes.decode("utf-8")

        connection_type = route_config.get("connection_type", "UNKNOWN")
        if connection_type == "UNKNOWN" and outbound_route:
            if outbound_route.get("as2_partner_id"):
                connection_type = "AS2"
            elif outbound_route.get("sftp_partner_id"):
                connection_type = "SFTP"

        await self.repository.save_edi_message(
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
        await self.repository.publish_outbox_event(
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
        logger.info(f"Successfully transformed JSON to EDI for trace_id={trace_id}")
