import logging
from typing import Any
from uuid import UUID

from api.core.uow import UnitOfWork

logger = logging.getLogger(__name__)


class TradingPartnerResolverService:
    """
    Domain service responsible for resolving a trading partner's name
    based on the current route and business metadata embedded in EDI JSONs.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def resolve_trading_partner_name(
        self, msg: Any, edi_jsons: list[Any]
    ) -> tuple[str | None, str | None]:

        trading_partner_name = None
        connection_type = None

        outbound_route_id = getattr(msg, "outbound_route_id", None)
        if outbound_route_id:
            try:
                # We expect msg to be an EdiMessageDTO now, but we'll tolerate Any
                # Wait, getting the route requires checking outbound routes
                route = None
                if self.uow.outbound_routes:
                    route = await self.uow.outbound_routes.get_outbound_route_by_trading_partner_id(
                        getattr(msg, "tenant_id", 0), outbound_route_id
                    )

                if route:
                    if route.as2_partner_id:
                        partner = await self.uow.as2_partners.get_as2_partner(
                            0, route.as2_partner_id
                        )
                        if partner:
                            trading_partner_name = partner.name
                        connection_type = "AS2"
                    elif route.sftp_partner_id:
                        partner = await self.uow.sftp_partners.get_sftp_partner(
                            getattr(msg, "tenant_id", 0), route.sftp_partner_id
                        )
                        if partner:
                            trading_partner_name = partner.name
                        connection_type = "SFTP"
            except Exception:
                logger.warning(
                    "Failed to resolve trading_partner_name from outbound route "
                    f"for trace_id={msg.trace_id}",
                    exc_info=True,
                )

        if not trading_partner_name:
            partner_ids = []
            for j in edi_jsons:
                bm = getattr(j, "business_metadata", None) or {}
                routing = bm.get("_routing", {})
                pid = routing.get("trading_partner_id")
                if pid:
                    import contextlib

                    with contextlib.suppress(ValueError):
                        partner_ids.append(UUID(pid))

            if partner_ids:
                try:
                    # Look up by ID directly
                    for pid in partner_ids:
                        partner = await self.uow.as2_partners.get_as2_partner(0, pid)
                        if partner:
                            trading_partner_name = partner.name
                            break
                        partner = await self.uow.sftp_partners.get_sftp_partner(
                            getattr(msg, "tenant_id", 0), pid
                        )
                        if partner:
                            trading_partner_name = partner.name
                            break
                except Exception:
                    logger.warning(
                        "Failed to resolve trading_partner_name from business_metadata "
                        f"for trace_id={msg.trace_id}",
                        exc_info=True,
                    )

        if not trading_partner_name and getattr(msg, "direction", None) == "INBOUND":
            try:
                sender = getattr(msg, "sender_id", None)
                receiver = getattr(msg, "receiver_id", None)
                tenant_id = getattr(msg, "tenant_id", 0)
                if sender and receiver:
                    t_type = None
                    if edi_jsons:
                        t_type = getattr(edi_jsons[0], "transaction_type", None)

                    if hasattr(self.uow, "inbound_routes") and self.uow.inbound_routes:
                        route = await self.uow.inbound_routes.get_inbound_route(
                            sender, receiver, tenant_id, t_type
                        )
                        if route:
                            # Prefer the AS2 partner name (connection_type = AS2).
                            # AS2 Partners are global (tenant_id=0), so always query with 0.
                            if getattr(route, "as2_partner_id", None) and self.uow.as2_partners:
                                partner = await self.uow.as2_partners.get_as2_partner(
                                    0, route.as2_partner_id
                                )
                                if partner:
                                    trading_partner_name = partner.name
                                    connection_type = "AS2"

                            # Then try SFTP partner (connection_type = SFTP)
                            elif (
                                getattr(route, "sftp_partner_id", None)
                                and hasattr(self.uow, "sftp_partners")
                                and self.uow.sftp_partners
                            ):
                                partner = await self.uow.sftp_partners.get_sftp_partner(
                                    tenant_id, route.sftp_partner_id
                                )
                                if partner:
                                    trading_partner_name = partner.name
                                    connection_type = "SFTP"

                            # Final fallback — resolve via webhook URL
                            elif (
                                getattr(route, "webhook_id", None)
                                and hasattr(self.uow, "webhooks")
                                and self.uow.webhooks
                            ):
                                wh = await self.uow.webhooks.get_webhook(
                                    tenant_id, route.webhook_id
                                )
                                if wh and getattr(wh, "url", None):
                                    trading_partner_name = wh.url
            except Exception:
                logger.warning(
                    "Failed to resolve trading_partner_name from inbound route "
                    f"for trace_id={msg.trace_id}",
                    exc_info=True,
                )

        return trading_partner_name, connection_type
