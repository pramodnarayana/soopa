import contextlib
import logging
from typing import Any

from database.models.control_plane import AS2Partner, SFTPPartner
from database.models.data_plane import InboundRoute, OutboundRoute
from domain.models import ConnectionType, Direction
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.webhooks import Webhook

logger = logging.getLogger(__name__)


class RoutingResolutionService:
    """
    Resolves the human-readable trading partner name and connection type for a given message.
    This is strictly an API-level View/Projection concern for presenting transaction
    details in the frontend UI.
    """

    def __init__(self, global_session: AsyncSession, tenant_session: AsyncSession | None):
        self.global_session = global_session
        self.tenant_session = tenant_session

    async def resolve_routing_context(
        self, msg: Any, edi_jsons: list[Any]
    ) -> tuple[str | None, str | None]:
        if (
            getattr(msg, "trading_partner_id", None)
            or getattr(msg, "direction", None) == Direction.OUTBOUND
        ):
            return await self._resolve_outbound_routing(msg, edi_jsons)
        return await self._resolve_inbound_routing(msg, edi_jsons)

    async def _resolve_outbound_routing(
        self, msg: Any, edi_jsons: list[Any]
    ) -> tuple[str | None, str | None]:
        """
        Resolves outbound routing by first checking explicit route overrides,
        then falling back to business_metadata from the EDI JSON.
        """
        # 1. Try to resolve via trading_partner_id on the message
        if getattr(msg, "trading_partner_id", None) and self.tenant_session:
            try:
                route = (
                    await self.tenant_session.execute(
                        select(OutboundRoute).where(
                            OutboundRoute.trading_partner_id == msg.trading_partner_id,
                            OutboundRoute.active.is_(True),
                        )
                    )
                ).scalar_one_or_none()

                if route:
                    if route.as2_partner_id:
                        res = await self.global_session.execute(
                            select(AS2Partner.name).where(AS2Partner.id == route.as2_partner_id)
                        )
                        name = res.scalar_one_or_none()
                        if name:
                            return name, ConnectionType.AS2

                    if route.sftp_partner_id:
                        res = await self.global_session.execute(
                            select(SFTPPartner.name).where(SFTPPartner.id == route.sftp_partner_id)
                        )
                        name = res.scalar_one_or_none()
                        if name:
                            return name, ConnectionType.SFTP
            except Exception:
                logger.warning(
                    "Failed to resolve trading_partner_name from outbound route "
                    f"for trace_id={msg.trace_id}",
                    exc_info=True,
                )

        # 2. Fallback to business_metadata from EDI JSON
        return await self._resolve_business_metadata_fallback(msg, edi_jsons)

    async def _resolve_inbound_routing(
        self, msg: Any, edi_jsons: list[Any]
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
            as2_from = getattr(msg, "as2_sender_id", None)
            if as2_from and msg.connection_type == ConnectionType.AS2:
                res = await self.global_session.execute(
                    select(AS2Partner.name).where(AS2Partner.as2_id == as2_from)
                )
                name = res.scalar_one_or_none()
                if name:
                    return name, ConnectionType.AS2

            # 3. Fallback for non-AS2 inbound (SFTP/webhook): look up via inbound route
            if self.tenant_session:
                t_type = edi_jsons[0].transaction_type if edi_jsons else None
                stmt = select(InboundRoute).where(
                    InboundRoute.isa_sender_id == msg.sender_id,
                    InboundRoute.isa_receiver_id == msg.receiver_id,
                    InboundRoute.active.is_(True),
                )
                if t_type:
                    stmt = stmt.where(InboundRoute.transaction_type == t_type)
                inbound_route = (await self.tenant_session.execute(stmt)).scalars().first()

                if inbound_route:
                    if inbound_route.sftp_partner_id:
                        res = await self.global_session.execute(
                            select(SFTPPartner.name).where(
                                SFTPPartner.id == inbound_route.sftp_partner_id
                            )
                        )
                        name = res.scalar_one_or_none()
                        if name:
                            return name, ConnectionType.SFTP

                    elif inbound_route.webhook_id:
                        res = await self.global_session.execute(
                            select(Webhook.url).where(Webhook.id == inbound_route.webhook_id)
                        )
                        webhook_url = res.scalar_one_or_none()
                        if webhook_url:
                            return webhook_url, ConnectionType.WEBHOOK
        except Exception:
            logger.warning(
                f"Failed to resolve trading_partner_name for inbound trace_id={msg.trace_id}",
                exc_info=True,
            )

        return None, msg.connection_type

    async def _resolve_business_metadata_fallback(
        self, msg: Any, edi_jsons: list[Any]
    ) -> tuple[str | None, str | None]:
        """
        Attempts to resolve partner name via explicit business metadata overrides in the EDI payload.
        """
        if not edi_jsons:
            return None, msg.connection_type

        partner_ids = []
        for j in edi_jsons:
            bm = getattr(j, "business_metadata", {}) or {}
            routing = bm.get("_routing", {})
            pid = routing.get("trading_partner_id")
            if pid:
                with contextlib.suppress(ValueError):
                    partner_ids.append(str(pid))

        if partner_ids:
            try:
                res = await self.global_session.execute(
                    select(AS2Partner.name).where(AS2Partner.id.in_(partner_ids))
                )
                name = res.scalars().first()
                if name:
                    return name, msg.connection_type

                res = await self.global_session.execute(
                    select(SFTPPartner.name).where(SFTPPartner.id.in_(partner_ids))
                )
                name = res.scalars().first()
                if name:
                    return name, msg.connection_type
            except Exception:
                logger.warning(
                    "Failed to resolve trading_partner_name from business_metadata "
                    f"for trace_id={msg.trace_id}",
                    exc_info=True,
                )

        return None, msg.connection_type
