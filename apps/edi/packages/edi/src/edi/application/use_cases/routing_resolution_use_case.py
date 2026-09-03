import contextlib

import structlog

from edi.application.dtos.transactions import EdiJsonDTO, EdiMessageDTO
from edi.domain.models.base import ConnectionType, Direction
from edi.ports.outbound.routing_resolver_repository import RoutingResolverRepositoryPort

logger = structlog.get_logger(__name__)


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
        if msg.trading_partner_id or msg.direction == Direction.OUTBOUND:
            return await self._resolve_outbound_routing(msg, edi_jsons)
        return await self._resolve_inbound_routing(msg, edi_jsons)

    async def _resolve_outbound_routing(
        self, msg: EdiMessageDTO, edi_jsons: list[EdiJsonDTO]
    ) -> tuple[str | None, str | None]:
        """
        Resolves outbound routing by first checking explicit route overrides,
        then falling back to business_metadata from the EDI JSON.
        """
        # 1. Try to resolve via trading_partner_id on the message
        tp_id = msg.trading_partner_id
        if tp_id:
            try:
                res = await self.repository.resolve_outbound_route(tp_id)
                if res:
                    return res
            except Exception as e:
                logger.exception(
                    "outbound_route_resolution_failed",
                    trace_id=msg.trace_id,
                    trading_partner_id=tp_id,
                )
                raise RuntimeError(
                    f"Outbound route resolution failed for trace_id={msg.trace_id}"
                ) from e

        # 2. Fallback to business_metadata from EDI JSON
        return await self._resolve_business_metadata_fallback(msg, edi_jsons)

    async def _resolve_inbound_routing(
        self, msg: EdiMessageDTO, edi_jsons: list[EdiJsonDTO]
    ) -> tuple[str | None, str | None]:
        """
        Resolves inbound routing by checking AS2 attributes first, then falling
        back to the database InboundRoute mappings.
        """
        # 1. Fallback to business metadata if provided (e.g. injected during translation)
        name, c_type = await self._resolve_business_metadata_fallback(msg, edi_jsons)
        if name:
            return name, c_type

        try:
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

    async def _resolve_business_metadata_fallback(
        self, msg: EdiMessageDTO, edi_jsons: list[EdiJsonDTO]
    ) -> tuple[str | None, str | None]:
        """
        Attempts to resolve partner name via explicit business metadata overrides in the EDI payload.
        """
        if not edi_jsons:
            return None, msg.connection_type

        partner_ids = []
        for j in edi_jsons:
            bm = j.business_metadata or {}
            routing = bm.get("_routing")
            if isinstance(routing, dict):
                pid = routing.get("trading_partner_id")
                if pid:
                    with contextlib.suppress(ValueError):
                        partner_ids.append(str(pid))

        if partner_ids:
            try:
                name = await self.repository.resolve_business_metadata(partner_ids)
                if name:
                    return name, msg.connection_type
            except Exception as e:
                logger.exception(
                    "business_metadata_route_resolution_failed",
                    trace_id=msg.trace_id,
                )
                raise RuntimeError(
                    f"Business metadata route resolution failed for trace_id={msg.trace_id}"
                ) from e

        return None, msg.connection_type
