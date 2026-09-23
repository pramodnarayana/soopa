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
        self, msg: EdiMessageDTO | None, edi_jsons: list[EdiJsonDTO]
    ) -> tuple[str | None, str | None]:
        trace_id = msg.trace_id if msg else None
        direction_source = "edi_message" if msg else "edi_json[0]"

        if msg is None:
            # Outbound replay race window: EdiJson is committed first; EdiMessage is
            # created asynchronously by the transform worker. Infer direction from EdiJson.
            direction = edi_jsons[0].direction if edi_jsons else None
            logger.info(
                "routing_resolution.msg_absent",
                trace_id=trace_id,
                inferred_direction=direction,
                direction_source=direction_source,
                edi_json_count=len(edi_jsons),
            )
            if direction == EdiDirection.OUTBOUND:
                return await self._resolve_outbound_routing(msg, edi_jsons)
            return await self._resolve_inbound_routing(msg, edi_jsons)

        if msg.trading_partner_id or msg.direction == EdiDirection.OUTBOUND:
            return await self._resolve_outbound_routing(msg, edi_jsons)
        return await self._resolve_inbound_routing(msg, edi_jsons)

    async def _resolve_outbound_routing(
        self, msg: EdiMessageDTO | None, edi_jsons: list[EdiJsonDTO]
    ) -> tuple[str | None, str | None]:
        """
        Resolves outbound routing by first checking explicit route overrides,
        then falling back to business_metadata from the EDI JSON.
        """
        trace_id = msg.trace_id if msg else None
        trading_partner_id = msg.trading_partner_id if msg else None
        metadata_partner_ids = _routing_partner_ids(edi_jsons)

        logger.debug(
            "routing_resolution.outbound.started",
            trace_id=trace_id,
            trading_partner_id=trading_partner_id,
            metadata_partner_ids=metadata_partner_ids,
        )

        try:
            if msg and msg.trading_partner_id:
                res = await self.repository.resolve_outbound_route(msg.trading_partner_id)
                if res:
                    logger.debug(
                        "routing_resolution.outbound.resolved_via_trading_partner",
                        trace_id=trace_id,
                        trading_partner_id=msg.trading_partner_id,
                    )
                    return res
                # Do not fall back to business metadata if a specific trading partner ID was
                # requested but not found in the routing table.
                logger.info(
                    "routing_resolution.outbound.trading_partner_not_found",
                    trace_id=trace_id,
                    trading_partner_id=msg.trading_partner_id,
                )
                return None, msg.connection_type if msg else None

            for tp_id in metadata_partner_ids:
                res = await self.repository.resolve_outbound_route(tp_id)
                if res:
                    logger.debug(
                        "routing_resolution.outbound.resolved_via_metadata",
                        trace_id=trace_id,
                        metadata_trading_partner_id=tp_id,
                    )
                    return res

            if metadata_partner_ids:
                partner_name = await self.repository.resolve_business_metadata(metadata_partner_ids)
                if partner_name:
                    logger.debug(
                        "routing_resolution.outbound.resolved_via_business_metadata",
                        trace_id=trace_id,
                    )
                    return partner_name, msg.connection_type if msg else None

        except Exception as e:
            logger.exception(
                "routing_resolution.outbound.failed",
                trace_id=trace_id,
                trading_partner_id=trading_partner_id,
                reason=str(e),
            )
            raise RuntimeError(
                f"Outbound route resolution failed for trace_id={trace_id or 'unknown'}"
            ) from e

        # No routing match found — degrade gracefully, UI will show without partner name.
        logger.info(
            "routing_resolution.outbound.unresolved",
            trace_id=trace_id,
            trading_partner_id=trading_partner_id,
            metadata_partner_ids=metadata_partner_ids,
        )
        return None, msg.connection_type if msg else None

    async def _resolve_inbound_routing(
        self, msg: EdiMessageDTO | None, edi_jsons: list[EdiJsonDTO]
    ) -> tuple[str | None, str | None]:
        """
        Resolves inbound routing by checking AS2 attributes first, then falling
        back to the database InboundRoute mappings.
        """
        trace_id = msg.trace_id if msg else None

        logger.debug(
            "routing_resolution.inbound.started",
            trace_id=trace_id,
            has_msg=msg is not None,
        )

        try:
            if msg is not None:
                # 1. For AS2 inbound: look up the AS2Partner by as2_sender_id (AS2-From)
                as2_from = msg.as2_sender_id
                if as2_from and msg.connection_type == ConnectionType.AS2:
                    res = await self.repository.resolve_as2_inbound(as2_from)
                    if res:
                        logger.debug(
                            "routing_resolution.inbound.resolved_via_as2",
                            trace_id=trace_id,
                            as2_sender_id=as2_from,
                        )
                        return res

                # 2. Fallback for non-AS2 inbound (SFTP/webhook): look up via inbound route
                t_type = edi_jsons[0].transaction_type if edi_jsons else None
                res = await self.repository.resolve_inbound_route(
                    msg.sender_id or "", msg.receiver_id or "", t_type
                )
                if res:
                    logger.debug(
                        "routing_resolution.inbound.resolved_via_route",
                        trace_id=trace_id,
                        sender_id=msg.sender_id,
                        receiver_id=msg.receiver_id,
                    )
                    return res

        except Exception as e:
            logger.exception(
                "routing_resolution.inbound.failed",
                trace_id=trace_id,
                reason=str(e),
            )
            raise RuntimeError(
                f"Inbound route resolution failed for trace_id={trace_id or 'unknown'}"
            ) from e

        logger.info(
            "routing_resolution.inbound.unresolved",
            trace_id=trace_id,
            has_msg=msg is not None,
        )
        return None, msg.connection_type if msg else None
