from typing import Any, Self

from api.adapters.repository import SqlAlchemyControlPlaneRepository, SqlAlchemyDataPlaneRepository
from sqlalchemy.ext.asyncio import AsyncSession


class UnitOfWork:
    """
    Unit of Work (UoW) pattern for the API layer.
    Manages the lifecycle of database transactions across both the global control plane
    and the tenant data plane schemas.
    """

    def __init__(
        self,
        global_session: AsyncSession,
        tenant_session: AsyncSession | None = None,
    ) -> None:
        self.global_session = global_session
        self.tenant_session = tenant_session
        self.control_plane = SqlAlchemyControlPlaneRepository(global_session)
        self.data_plane = SqlAlchemyDataPlaneRepository(tenant_session) if tenant_session else None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        """Commits transactions on both active sessions."""
        try:
            if self.tenant_session:
                await self.tenant_session.flush()
            await self.global_session.flush()

            if self.tenant_session:
                await self.tenant_session.commit()
            await self.global_session.commit()
        except Exception:
            await self.rollback()
            raise

    async def resolve_trading_partner_name(
        self, msg: Any, edi_jsons: list[Any]
    ) -> tuple[str | None, str | None]:
        import contextlib
        import logging
        import uuid

        from database.models.control_plane import AS2Partner, SFTPPartner, Webhook
        from database.models.data_plane import InboundRoute, OutboundRoute
        from sqlalchemy import select

        logger = logging.getLogger(__name__)
        trading_partner_name = None
        connection_type = None

        outbound_route_id = getattr(msg, "outbound_route_id", None)
        if outbound_route_id:
            try:
                route = None
                if self.tenant_session:
                    route_res = await self.tenant_session.execute(
                        select(OutboundRoute).where(OutboundRoute.id == outbound_route_id)
                    )
                    route = route_res.scalar_one_or_none()
                if route:
                    if route.as2_partner_id:
                        res = await self.global_session.execute(
                            select(AS2Partner.name).where(AS2Partner.id == route.as2_partner_id)
                        )
                        trading_partner_name = res.scalar_one_or_none()
                        connection_type = "AS2"
                    elif route.sftp_partner_id:
                        res = await self.global_session.execute(
                            select(SFTPPartner.name).where(SFTPPartner.id == route.sftp_partner_id)
                        )
                        trading_partner_name = res.scalar_one_or_none()
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
                bm = j.business_metadata or {}
                routing = bm.get("_routing", {})
                pid = routing.get("trading_partner_id")
                if pid:
                    with contextlib.suppress(ValueError):
                        partner_ids.append(uuid.UUID(pid))

            if partner_ids:
                try:
                    res = await self.global_session.execute(
                        select(AS2Partner.name).where(AS2Partner.id.in_(partner_ids))
                    )
                    name = res.scalars().first()
                    if name:
                        trading_partner_name = name
                    else:
                        res = await self.global_session.execute(
                            select(SFTPPartner.name).where(SFTPPartner.id.in_(partner_ids))
                        )
                        name = res.scalars().first()
                        if name:
                            trading_partner_name = name
                except Exception:
                    logger.warning(
                        "Failed to resolve trading_partner_name from business_metadata "
                        f"for trace_id={msg.trace_id}",
                        exc_info=True,
                    )

        if not trading_partner_name and msg.direction == "INBOUND":
            try:
                t_type = None
                if edi_jsons:
                    t_type = edi_jsons[0].transaction_type

                if self.tenant_session:
                    stmt = select(InboundRoute).where(
                        InboundRoute.isa_sender_id == msg.sender_id,
                        InboundRoute.isa_receiver_id == msg.receiver_id,
                        InboundRoute.active.is_(True),
                    )
                    if t_type:
                        stmt = stmt.where(InboundRoute.transaction_type == t_type)
                    inbound_route = (await self.tenant_session.execute(stmt)).scalars().first()

                    if inbound_route and inbound_route.webhook_id:
                        stmt2 = select(Webhook.url).where(Webhook.id == inbound_route.webhook_id)
                        webhook_url = (
                            await self.global_session.execute(stmt2)
                        ).scalar_one_or_none()
                        if webhook_url:
                            trading_partner_name = f"Webhook: {webhook_url}"
            except Exception:
                logger.warning(
                    "Failed to resolve trading_partner_name from inbound route/webhook "
                    f"for trace_id={msg.trace_id}",
                    exc_info=True,
                )

        return trading_partner_name, connection_type

    async def rollback(self) -> None:
        """Rolls back transactions on both active sessions."""
        await self.global_session.rollback()
        if self.tenant_session:
            await self.tenant_session.rollback()
