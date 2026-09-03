import structlog

from edi.application.dtos.transactions import EdiJsonDTO, EdiMessageDTO
from edi.domain.enums import ConnectionType, EdiDirection
from edi.ports.outbound.routing_resolver_repository import RoutingResolverRepositoryPort

logger = structlog.get_logger(__name__)


def _routing_partner_ids(edi_jsons: list[EdiJsonDTO]) -> list[str]:
    partner_ids: list[str] = []
    for edi_json in edi_jsons:
        metadata = edi_json.business_metadata or {}
        routing_metadata = metadata.get("_routing")
        if isinstance(routing_metadata, dict):
            partner_id = routing_metadata.get("trading_partner_id")
            if isinstance(partner_id, str) and partner_id and partner_id not in partner_ids:
                partner_ids.append(partner_id)
    return partner_ids


class RoutingResolutionUseCase:
    """
    Resolves the human-readable trading partner name and connection type for a given message.
    This is strictly an API-level View/Projection concern for presenting transaction
    details in the frontend UI.
    """

    def __init__(self, repository: RoutingResolverRepositoryPort):
        self.repository = repository

    async def resolve_routing_context(
        self, msg: EdiMessageDTO, edi_jsons: list[EdiJsonDTO]
    ) -> tuple[str | None, str | None]:
        if msg.trading_partner_id or msg.direction == EdiDirection.OUTBOUND:
            return await self._resolve_outbound_routing(msg, edi_jsons)
        return await self._resolve_inbound_routing(msg, edi_jsons)

    async def _resolve_outbound_routing(
        self, msg: EdiMessageDTO, edi_jsons: list[EdiJsonDTO]
    ) -> tuple[str | None, str | None]:
        """
        Resolves outbound routing by first checking explicit route overrides,
        then falling back to business_metadata from the EDI JSON.
        """
        # 1. Try to resolve via trading_partner_id on the message, then persisted routing metadata.
        metadata_partner_ids = _routing_partner_ids(edi_jsons)
        tp_id = msg.trading_partner_id or next(iter(metadata_partner_ids), None)

        try:
            if tp_id:
                res = await self.repository.resolve_outbound_route(tp_id)
                if res:
                    return res

            partner_ids = metadata_partner_ids or ([tp_id] if tp_id else [])
            partner_name = await self.repository.resolve_business_metadata(partner_ids)
            if partner_name:
                return partner_name, msg.connection_type
        except Exception as e:
            logger.exception(
                "outbound_route_resolution_failed",
                trace_id=msg.trace_id,
                trading_partner_id=tp_id,
            )
            raise RuntimeError(
                f"Outbound route resolution failed for trace_id={msg.trace_id}"
            ) from e

        # If no trading partner is available, we cannot resolve the route.
        return None, msg.connection_type

    async def _resolve_inbound_routing(
        self, msg: EdiMessageDTO, edi_jsons: list[EdiJsonDTO]
    ) -> tuple[str | None, str | None]:
        """
        Resolves inbound routing by checking AS2 attributes first, then falling
        back to the database InboundRoute mappings.
        """

        try:
            metadata_partner_ids = _routing_partner_ids(edi_jsons)
            if metadata_partner_ids:
                partner_name = await self.repository.resolve_business_metadata(metadata_partner_ids)
                if partner_name:
                    return partner_name, msg.connection_type

            # 2. For AS2 inbound: look up the AS2Partner by as2_sender_id (AS2-From)
            as2_from = msg.as2_sender_id
            if as2_from and msg.connection_type == ConnectionType.AS2:
                res = await self.repository.resolve_as2_inbound(as2_from)
                if res:
                    return res

            # 3. Fallback for non-AS2 inbound (SFTP/webhook): look up via inbound route
            t_type = edi_jsons[0].transaction_type if edi_jsons else None
            res = await self.repository.resolve_inbound_route(
                msg.sender_id or "", msg.receiver_id or "", t_type
            )
            if res:
                return res

        except Exception as e:
            logger.exception(
                "inbound_route_resolution_failed",
                trace_id=msg.trace_id,
            )
            raise RuntimeError(
                f"Inbound route resolution failed for trace_id={msg.trace_id}"
            ) from e

        return None, msg.connection_type
