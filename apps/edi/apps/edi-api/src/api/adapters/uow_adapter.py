from typing import Any, Self

from sqlalchemy.ext.asyncio import AsyncSession

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


class SqlAlchemyControlPlaneUnitOfWork:
    """
    Concrete Unit of Work for the Control Plane (Global Schema).
    Manages transactions exclusively for global configuration and routing tables.
    """

    def __init__(self, global_session: AsyncSession) -> None:
        self.global_session = global_session
        from typing import cast

        from database.base_repository import GlobalSession

        gs = cast(GlobalSession, global_session)

        self.api_tokens = SqlAlchemyApiTokenRepository(gs)
        self.as2_partners = SqlAlchemyAS2TradingPartnerRepository(gs)
        self.as2_partnerships = SqlAlchemyAS2PartnershipRepository(gs)
        self.inbound_routes = SqlAlchemyInboundRouteRepository(gs)
        self.outbound_routes = SqlAlchemyOutboundRouteRepository(gs)
        self.control_plane_outbox = SqlAlchemyControlPlaneOutboxRepository(gs)
        self.sftp_partners = SqlAlchemySFTPPartnerRepository(gs)
        self.tenants = SqlAlchemyTenantRepository(gs)
        self.webhooks = SqlAlchemyWebhookRepository(gs)
        self.edi_headers = SqlAlchemyEdiHeaderRepository(gs)
        self.platform_settings = SqlAlchemyPlatformSettingsRepository(gs)

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
        """Commits the transaction on the global session."""
        try:
            await self.global_session.flush()
            await self.global_session.commit()
        except Exception:
            await self.rollback()
            raise

    async def rollback(self) -> None:
        """Rolls back the transaction on the global session."""
        await self.global_session.rollback()


class SqlAlchemyDataPlaneUnitOfWork:
    """
    Concrete Unit of Work for the Data Plane (Tenant Schema).
    Manages transactions exclusively for a specific tenant's data and message processing.
    """

    def __init__(self, tenant_session: AsyncSession) -> None:
        self.tenant_session = tenant_session
        from typing import cast

        from database.base_repository import TenantSession

        ts = cast(TenantSession, tenant_session)

        self.transactions = SqlAlchemyTransactionRepository(ts)
        self.data_plane_outbox = SqlAlchemyDataPlaneOutboxRepository(ts)

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
        """Commits the transaction on the tenant session."""
        try:
            await self.tenant_session.flush()
            await self.tenant_session.commit()
        except Exception:
            await self.rollback()
            raise

    async def rollback(self) -> None:
        """Rolls back the transaction on the tenant session."""
        await self.tenant_session.rollback()
