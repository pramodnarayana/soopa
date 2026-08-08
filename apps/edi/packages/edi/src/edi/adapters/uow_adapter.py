from typing import Any, Self

from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.as2_partner_repository import SqlAlchemyAS2TradingPartnerRepository
from edi.adapters.as2_partnership_repository import SqlAlchemyAS2PartnershipRepository
from edi.adapters.edi_header_repository import SqlAlchemyEdiHeaderRepository
from edi.adapters.inbound_route_repository import SqlAlchemyInboundRouteRepository
from edi.adapters.outbound_route_repository import SqlAlchemyOutboundRouteRepository
from edi.adapters.outbox_repository import (
    SqlAlchemyControlPlaneOutboxRepository,
    SqlAlchemyDataPlaneOutboxRepository,
)
from edi.adapters.platform_settings_repository import SqlAlchemyPlatformSettingsRepository
from edi.adapters.sftp_repository import SqlAlchemySFTPPartnerRepository
from edi.adapters.tenant_repository import SqlAlchemyTenantRepository
from edi.adapters.transaction_repository import SqlAlchemyTransactionRepository
from edi.adapters.webhook_repository import SqlAlchemyWebhookRepository
from edi.ports.as2_partner_repository import AS2TradingPartnerRepositoryPort
from edi.ports.as2_partnership_repository import AS2PartnershipRepositoryPort
from edi.ports.edi_header_repository import EdiHeaderRepositoryPort
from edi.ports.inbound_route_repository import InboundRouteRepositoryPort
from edi.ports.outbound_route_repository import OutboundRouteRepositoryPort
from edi.ports.outbox_repository import (
    ControlPlaneOutboxRepositoryPort,
    DataPlaneOutboxRepositoryPort,
)
from edi.ports.platform_settings_repository import PlatformSettingsRepositoryPort
from edi.ports.sftp_repository import SFTPPartnerRepositoryPort
from edi.ports.tenant_repository import TenantRepositoryPort
from edi.ports.transaction_repository import TransactionRepositoryPort
from edi.ports.webhook_repository import WebhookRepositoryPort


class SqlAlchemyControlPlaneUnitOfWork:
    """
    Concrete Unit of Work for the Control Plane (Global Schema).
    Manages transactions exclusively for global configuration and routing tables.
    """

    as2_partners: AS2TradingPartnerRepositoryPort
    as2_partnerships: AS2PartnershipRepositoryPort
    inbound_routes: InboundRouteRepositoryPort
    outbound_routes: OutboundRouteRepositoryPort
    control_plane_outbox: ControlPlaneOutboxRepositoryPort
    sftp_partners: SFTPPartnerRepositoryPort
    tenants: TenantRepositoryPort
    webhooks: WebhookRepositoryPort
    edi_headers: EdiHeaderRepositoryPort
    platform_settings: PlatformSettingsRepositoryPort

    def __init__(self, global_session: AsyncSession) -> None:
        self.global_session = global_session
        from typing import cast

        from database.base_repository import GlobalSession

        gs = cast(GlobalSession, global_session)

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

    transactions: TransactionRepositoryPort
    data_plane_outbox: DataPlaneOutboxRepositoryPort

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
