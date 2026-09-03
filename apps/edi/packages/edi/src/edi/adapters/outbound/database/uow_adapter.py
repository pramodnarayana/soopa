from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from database.uow import BaseSqlAlchemyUnitOfWork
from edi.adapters.outbound.database.as2_partner_repository import (
    SqlAlchemyAS2TradingPartnerRepository,
)
from edi.adapters.outbound.database.as2_partnership_repository import (
    SqlAlchemyAS2PartnershipRepository,
)
from edi.adapters.outbound.database.base_repository import GlobalSession, TenantSession
from edi.adapters.outbound.database.edi_header_repository import SqlAlchemyEdiHeaderRepository
from edi.adapters.outbound.database.inbound_route_repository import SqlAlchemyInboundRouteRepository
from edi.adapters.outbound.database.outbound_route_repository import (
    SqlAlchemyOutboundRouteRepository,
)
from edi.adapters.outbound.database.outbox_repository import (
    SqlAlchemyControlPlaneOutboxRepository,
)
from edi.adapters.outbound.database.platform_settings_repository import (
    SqlAlchemyPlatformSettingsRepository,
)
from edi.adapters.outbound.database.tenant_repository import SqlAlchemyTenantRepository
from edi.adapters.outbound.database.trace_repository import SqlAlchemyTraceRepository
from edi.adapters.outbound.database.transaction_repository import SqlAlchemyTransactionRepository
from edi.adapters.outbound.sftp.sftp_repository import SqlAlchemySFTPPartnerRepository
from edi.ports.outbound.as2_partner_repository import AS2TradingPartnerRepositoryPort
from edi.ports.outbound.as2_partnership_repository import AS2PartnershipRepositoryPort
from edi.ports.outbound.control_plane_outbox_repository_port import (
    ControlPlaneOutboxRepositoryPort,
)
from edi.ports.outbound.edi_header_repository import EdiHeaderRepositoryPort
from edi.ports.outbound.inbound_route_repository import InboundRouteRepositoryPort
from edi.ports.outbound.outbound_route_repository import OutboundRouteRepositoryPort
from edi.ports.outbound.platform_settings_repository import PlatformSettingsRepositoryPort
from edi.ports.outbound.sftp_repository import SFTPPartnerRepositoryPort
from edi.ports.outbound.storage_port import StoragePort
from edi.ports.outbound.tenant_repository import TenantRepositoryPort
from edi.ports.outbound.trace_repository import TraceRepositoryPort
from edi.ports.outbound.transaction_repository import TransactionRepositoryPort


class SqlAlchemyControlPlaneUnitOfWork(BaseSqlAlchemyUnitOfWork):
    """
    Concrete Unit of Work for the Control Plane (Global Schema).
    Manages transactions exclusively for global configuration and routing tables.
    """

    as2_partners: AS2TradingPartnerRepositoryPort
    as2_partnerships: AS2PartnershipRepositoryPort
    inbound_routes: InboundRouteRepositoryPort
    outbound_routes: OutboundRouteRepositoryPort
    sftp_partners: SFTPPartnerRepositoryPort
    tenants: TenantRepositoryPort
    edi_headers: EdiHeaderRepositoryPort
    control_plane_outbox: ControlPlaneOutboxRepositoryPort
    platform_settings: PlatformSettingsRepositoryPort

    def __init__(self, global_session: AsyncSession) -> None:
        super().__init__(global_session)
        self.global_session = global_session

        gs = cast(GlobalSession, global_session)

        self.as2_partners = SqlAlchemyAS2TradingPartnerRepository(gs)
        self.as2_partnerships = SqlAlchemyAS2PartnershipRepository(gs)
        self.inbound_routes = SqlAlchemyInboundRouteRepository(gs)
        self.outbound_routes = SqlAlchemyOutboundRouteRepository(gs)
        self.sftp_partners = SqlAlchemySFTPPartnerRepository(gs)
        self.tenants = SqlAlchemyTenantRepository(gs)
        self.edi_headers = SqlAlchemyEdiHeaderRepository(gs)
        self.control_plane_outbox = SqlAlchemyControlPlaneOutboxRepository(gs)
        self.platform_settings = SqlAlchemyPlatformSettingsRepository(gs)


class SqlAlchemyDataPlaneUnitOfWork(BaseSqlAlchemyUnitOfWork):
    """
    Concrete Unit of Work for the Data Plane (Tenant Schema).
    Manages transactions exclusively for a specific tenant's data and message processing.
    """

    transactions: TransactionRepositoryPort
    traces: TraceRepositoryPort

    def __init__(self, tenant_session: AsyncSession, storage: StoragePort) -> None:
        super().__init__(tenant_session)
        self.tenant_session = tenant_session

        ts = cast(TenantSession, tenant_session)

        self.transactions = SqlAlchemyTransactionRepository(ts, storage)
        self.traces = SqlAlchemyTraceRepository(ts, storage)
