from typing import Any, Self

from api.adapters.api_token_repository import SqlAlchemyApiTokenRepository
from api.adapters.as2_partner_repository import SqlAlchemyAS2TradingPartnerRepository
from api.adapters.as2_partnership_repository import SqlAlchemyAS2PartnershipRepository
from api.adapters.edi_header_repository import SqlAlchemyEdiHeaderRepository
from api.adapters.inbound_route_repository import SqlAlchemyInboundRouteRepository
from api.adapters.outbound_route_repository import SqlAlchemyOutboundRouteRepository
from api.adapters.outbox_repository import (
    SqlAlchemyControlPlaneOutboxRepository,
    SqlAlchemyDataPlaneOutboxRepository,
)
from api.adapters.platform_settings_repository import SqlAlchemyPlatformSettingsRepository
from api.adapters.sftp_repository import SqlAlchemySFTPPartnerRepository
from api.adapters.tenant_repository import SqlAlchemyTenantRepository
from api.adapters.transaction_repository import SqlAlchemyTransactionRepository
from api.adapters.webhook_repository import SqlAlchemyWebhookRepository
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
        from typing import cast

        from database.base_repository import GlobalSession, TenantSession

        gs = cast(GlobalSession, global_session)
        ts = cast(TenantSession, tenant_session) if tenant_session else None

        self.api_tokens = SqlAlchemyApiTokenRepository(gs)
        self.as2_partners = SqlAlchemyAS2TradingPartnerRepository(gs)
        self.as2_partnerships = SqlAlchemyAS2PartnershipRepository(gs)
        self.inbound_routes = SqlAlchemyInboundRouteRepository(gs)
        self.outbound_routes = SqlAlchemyOutboundRouteRepository(gs)
        self.control_plane_outbox = SqlAlchemyControlPlaneOutboxRepository(gs)
        self._data_plane_outbox = SqlAlchemyDataPlaneOutboxRepository(ts) if ts else None
        self.sftp_partners = SqlAlchemySFTPPartnerRepository(gs)
        self.tenants = SqlAlchemyTenantRepository(gs)
        self.webhooks = SqlAlchemyWebhookRepository(gs)
        self.edi_headers = SqlAlchemyEdiHeaderRepository(gs)
        self.platform_settings = SqlAlchemyPlatformSettingsRepository(gs)

        self._transactions = SqlAlchemyTransactionRepository(ts) if ts else None

    @property
    def transactions(self) -> SqlAlchemyTransactionRepository:
        if not self._transactions:
            raise RuntimeError("Transaction repository requires an active tenant session.")
        return self._transactions

    @property
    def data_plane_outbox(self) -> SqlAlchemyDataPlaneOutboxRepository:
        if not self._data_plane_outbox:
            raise RuntimeError("Tenant outbox repository requires an active tenant session.")
        return self._data_plane_outbox

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: Any | None,
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
        from api.core.services.routing_resolver import RoutingResolutionService

        resolver = RoutingResolutionService(self.global_session, self.tenant_session)
        return await resolver.resolve_routing_context(msg, edi_jsons)

    async def rollback(self) -> None:
        """Rolls back transactions on both active sessions."""
        await self.global_session.rollback()
        if self.tenant_session:
            await self.tenant_session.rollback()
