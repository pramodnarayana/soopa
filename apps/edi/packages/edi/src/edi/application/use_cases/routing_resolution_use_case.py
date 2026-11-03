from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol

import structlog

from edi.application.responses import EdiJsonDTO, EdiMessageDTO
from edi.domain.routing.enums import ConnectionType, EdiDirection
from edi.domain.routing.inbound_route import InboundRoute
from edi.ports.outbound.as2_partner_repository import AS2TradingPartnerRepositoryPort
from edi.ports.outbound.inbound_route_repository import InboundRouteRepositoryPort
from edi.ports.outbound.outbound_route_repository import OutboundRouteRepositoryPort
from edi.ports.outbound.sftp_repository import SFTPPartnerRepositoryPort
from edi.ports.outbound.webhook_repository import WebhookRepositoryPort

logger = structlog.get_logger(__name__)


class RoutingResolutionUnitOfWorkPort(Protocol):
    """Structural Unit of Work slice exposing strictly 1-Aggregate-per-Repository ports."""

    inbound_routes: InboundRouteRepositoryPort
    outbound_routes: OutboundRouteRepositoryPort
    as2_partners: AS2TradingPartnerRepositoryPort
    sftp_partners: SFTPPartnerRepositoryPort
    webhooks: WebhookRepositoryPort


@dataclass(frozen=True, kw_only=True)
class ResolveRoutingContextQuery:
    tenant_id: str
    edi_message: EdiMessageDTO | None = None
    edi_jsons: Sequence[EdiJsonDTO] = ()


@dataclass(frozen=True, kw_only=True)
class ResolvedRoutingContextDTO:
    trading_partner_name: str | None = None
    connection_type: str | None = None

    def enrich_message(self, edi_message: EdiMessageDTO | None) -> EdiMessageDTO | None:
        """Return a copy of edi_message with connection_type populated if previously absent/UNKNOWN."""
        if (
            edi_message is not None
            and self.connection_type
            and (
                not edi_message.connection_type
                or edi_message.connection_type == ConnectionType.UNKNOWN.value
            )
        ):
            return replace(edi_message, connection_type=self.connection_type.upper())
        return edi_message


def _routing_partner_ids(edi_jsons: Sequence[EdiJsonDTO]) -> list[str]:
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
    Resolves the human-readable trading partner name and connection type for a trace
    exclusively through single-aggregate repositories on the Unit of Work.
    """

    def __init__(self, uow: RoutingResolutionUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, query: ResolveRoutingContextQuery) -> ResolvedRoutingContextDTO:
        msg = query.edi_message
        edi_jsons = query.edi_jsons
        trace_id = msg.trace_id if msg else None
        direction_source = "edi_message" if msg else "edi_json[0]"

        if msg is None:
            direction = edi_jsons[0].direction if edi_jsons else None
            logger.info(
                "routing_resolution.msg_absent",
                tenant_id=query.tenant_id,
                trace_id=trace_id,
                inferred_direction=direction,
                direction_source=direction_source,
                edi_json_count=len(edi_jsons),
            )
            if direction == EdiDirection.OUTBOUND:
                return await self._resolve_outbound_routing(query.tenant_id, msg, edi_jsons)
            return await self._resolve_inbound_routing(query.tenant_id, msg, edi_jsons)

        if msg.direction == EdiDirection.OUTBOUND:
            return await self._resolve_outbound_routing(query.tenant_id, msg, edi_jsons)
        return await self._resolve_inbound_routing(query.tenant_id, msg, edi_jsons)

    async def _resolve_outbound_partner(
        self, tenant_id: str, trading_partner_id: str
    ) -> ResolvedRoutingContextDTO | None:
        route = await self._uow.outbound_routes.get_outbound_route_by_trading_partner_id(
            tenant_id, trading_partner_id
        )
        if route is None or not route.active:
            return None

        if route.as2_partner_id:
            as2_partner = await self._uow.as2_partners.get_as2_partner(
                tenant_id, route.as2_partner_id
            )
            if as2_partner is not None:
                return ResolvedRoutingContextDTO(
                    trading_partner_name=as2_partner.name,
                    connection_type=ConnectionType.AS2.value,
                )

        if route.sftp_partner_id:
            sftp_partner = await self._uow.sftp_partners.get_sftp_partner(
                tenant_id, route.sftp_partner_id
            )
            if sftp_partner is not None:
                return ResolvedRoutingContextDTO(
                    trading_partner_name=sftp_partner.name,
                    connection_type=ConnectionType.SFTP.value,
                )

        return None

    async def _resolve_business_metadata_partner_name(
        self, tenant_id: str, partner_ids: list[str]
    ) -> str | None:
        if not partner_ids:
            return None

        as2_partners = await self._uow.as2_partners.get_as2_partners_by_ids(tenant_id, partner_ids)
        if as2_partners:
            return as2_partners[0].name

        sftp_partners = await self._uow.sftp_partners.get_sftp_partners_by_ids(
            tenant_id, partner_ids
        )
        if sftp_partners:
            return sftp_partners[0].name

        return None

    async def _resolve_outbound_routing(
        self,
        tenant_id: str,
        msg: EdiMessageDTO | None,
        edi_jsons: Sequence[EdiJsonDTO],
    ) -> ResolvedRoutingContextDTO:
        trace_id = msg.trace_id if msg else None
        trading_partner_id = msg.trading_partner_id if msg else None
        metadata_partner_ids = _routing_partner_ids(edi_jsons)

        logger.debug(
            "routing_resolution.outbound.started",
            tenant_id=tenant_id,
            trace_id=trace_id,
            trading_partner_id=trading_partner_id,
            metadata_partner_ids=metadata_partner_ids,
        )

        if msg and msg.trading_partner_id:
            resolved = await self._resolve_outbound_partner(tenant_id, msg.trading_partner_id)
            if resolved is not None:
                logger.debug(
                    "routing_resolution.outbound.resolved_via_trading_partner",
                    tenant_id=tenant_id,
                    trace_id=trace_id,
                    trading_partner_id=msg.trading_partner_id,
                )
                return resolved
            logger.info(
                "routing_resolution.outbound.trading_partner_not_found",
                tenant_id=tenant_id,
                trace_id=trace_id,
                trading_partner_id=msg.trading_partner_id,
            )
            return ResolvedRoutingContextDTO(
                trading_partner_name=None,
                connection_type=msg.connection_type,
            )

        for tp_id in metadata_partner_ids:
            resolved = await self._resolve_outbound_partner(tenant_id, tp_id)
            if resolved is not None:
                logger.debug(
                    "routing_resolution.outbound.resolved_via_metadata",
                    tenant_id=tenant_id,
                    trace_id=trace_id,
                    metadata_trading_partner_id=tp_id,
                )
                return resolved

        if metadata_partner_ids:
            partner_name = await self._resolve_business_metadata_partner_name(
                tenant_id, metadata_partner_ids
            )
            if partner_name:
                logger.debug(
                    "routing_resolution.outbound.resolved_via_business_metadata",
                    tenant_id=tenant_id,
                    trace_id=trace_id,
                )
                return ResolvedRoutingContextDTO(
                    trading_partner_name=partner_name,
                    connection_type=msg.connection_type if msg else None,
                )

        logger.info(
            "routing_resolution.outbound.unresolved",
            tenant_id=tenant_id,
            trace_id=trace_id,
            trading_partner_id=trading_partner_id,
            metadata_partner_ids=metadata_partner_ids,
        )
        return ResolvedRoutingContextDTO(
            trading_partner_name=None,
            connection_type=msg.connection_type if msg else None,
        )

    async def _resolve_inbound_route_destination(
        self,
        tenant_id: str,
        inbound_route: InboundRoute,
    ) -> ResolvedRoutingContextDTO | None:
        if inbound_route.as2_partner_id:
            as2_partner = await self._uow.as2_partners.get_as2_partner(
                tenant_id, inbound_route.as2_partner_id
            )
            if as2_partner is not None:
                return ResolvedRoutingContextDTO(
                    trading_partner_name=as2_partner.name,
                    connection_type=ConnectionType.AS2.value,
                )
        if inbound_route.sftp_partner_id:
            sftp_partner = await self._uow.sftp_partners.get_sftp_partner(
                tenant_id, inbound_route.sftp_partner_id
            )
            if sftp_partner is not None:
                return ResolvedRoutingContextDTO(
                    trading_partner_name=sftp_partner.name,
                    connection_type=ConnectionType.SFTP.value,
                )
        if inbound_route.webhook_id:
            webhook = await self._uow.webhooks.get_webhook(tenant_id, inbound_route.webhook_id)
            if webhook is not None:
                return ResolvedRoutingContextDTO(
                    trading_partner_name=webhook.url,
                    connection_type=ConnectionType.WEBHOOK.value,
                )
        return None

    async def _resolve_inbound_routing(
        self,
        tenant_id: str,
        msg: EdiMessageDTO | None,
        edi_jsons: Sequence[EdiJsonDTO],
    ) -> ResolvedRoutingContextDTO:
        trace_id = msg.trace_id if msg else None

        logger.debug(
            "routing_resolution.inbound.started",
            tenant_id=tenant_id,
            trace_id=trace_id,
            has_msg=msg is not None,
        )

        if msg is not None:
            as2_from = msg.as2_sender_id
            if as2_from and msg.connection_type == ConnectionType.AS2:
                as2_partner = await self._uow.as2_partners.get_as2_partner_by_as2_id(
                    tenant_id, as2_from
                )
                if as2_partner is not None:
                    logger.debug(
                        "routing_resolution.inbound.resolved_via_as2",
                        tenant_id=tenant_id,
                        trace_id=trace_id,
                        as2_sender_id=as2_from,
                    )
                    return ResolvedRoutingContextDTO(
                        trading_partner_name=as2_partner.name,
                        connection_type=ConnectionType.AS2.value,
                    )

            t_type = (edi_jsons[0].transaction_type if edi_jsons else None) or msg.transaction_type
            inbound_route = await self._uow.inbound_routes.get_inbound_route(
                msg.sender_id or "",
                msg.receiver_id or "",
                tenant_id,
                t_type,
            )
            if inbound_route is not None and inbound_route.active:
                resolved = await self._resolve_inbound_route_destination(tenant_id, inbound_route)
                if resolved is not None:
                    logger.debug(
                        "routing_resolution.inbound.resolved_via_route",
                        tenant_id=tenant_id,
                        trace_id=trace_id,
                        sender_id=msg.sender_id,
                        receiver_id=msg.receiver_id,
                    )
                    return resolved

        logger.info(
            "routing_resolution.inbound.unresolved",
            tenant_id=tenant_id,
            trace_id=trace_id,
            has_msg=msg is not None,
        )
        return ResolvedRoutingContextDTO(
            trading_partner_name=None,
            connection_type=msg.connection_type if msg else None,
        )
