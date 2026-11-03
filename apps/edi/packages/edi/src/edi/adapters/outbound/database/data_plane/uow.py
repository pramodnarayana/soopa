from sqlalchemy import CursorResult, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from strace.ports import TraceRepositoryPort

from database.uow import BaseSqlAlchemyUnitOfWork
from edi.adapters.outbound.database.models.data_plane import ProcessedEvent
from edi.ports.outbound.api_gateway_repository import ApiGatewayRepositoryPort
from edi.ports.outbound.as2_partner_repository import AS2TradingPartnerRepositoryPort
from edi.ports.outbound.as2_partnership_repository import AS2PartnershipRepositoryPort
from edi.ports.outbound.data_plane_outbox_repository_port import DataPlaneOutboxRepositoryPort
from edi.ports.outbound.edi_header_repository import EdiHeaderRepositoryPort
from edi.ports.outbound.edi_json_repository import EdiJsonRepositoryPort
from edi.ports.outbound.edi_message_repository import EdiMessageRepositoryPort
from edi.ports.outbound.inbound_route_repository import InboundRouteRepositoryPort
from edi.ports.outbound.outbound_route_repository import OutboundRouteRepositoryPort
from edi.ports.outbound.sftp_repository import SFTPPartnerRepositoryPort
from edi.ports.outbound.webhook_repository import WebhookRepositoryPort


class SqlAlchemyDataPlaneUnitOfWork(BaseSqlAlchemyUnitOfWork):
    """
    Concrete Unit of Work for the EDI Worker Data Plane.
    Collaborating repositories are injected via Ports from the Composition Root.
    """

    edi_messages: EdiMessageRepositoryPort
    edi_jsons: EdiJsonRepositoryPort
    api_gateway_receipts: ApiGatewayRepositoryPort
    traces: TraceRepositoryPort
    outbox: DataPlaneOutboxRepositoryPort
    inbound_routes: InboundRouteRepositoryPort
    outbound_routes: OutboundRouteRepositoryPort
    sftp_partners: SFTPPartnerRepositoryPort
    as2_partners: AS2TradingPartnerRepositoryPort
    as2_partnerships: AS2PartnershipRepositoryPort
    webhooks: WebhookRepositoryPort
    edi_headers: EdiHeaderRepositoryPort

    def __init__(
        self,
        tenant_session: AsyncSession,
        *,
        edi_messages: EdiMessageRepositoryPort,
        edi_jsons: EdiJsonRepositoryPort,
        api_gateway_receipts: ApiGatewayRepositoryPort,
        traces: TraceRepositoryPort,
        outbox: DataPlaneOutboxRepositoryPort,
        inbound_routes: InboundRouteRepositoryPort,
        outbound_routes: OutboundRouteRepositoryPort,
        sftp_partners: SFTPPartnerRepositoryPort,
        as2_partners: AS2TradingPartnerRepositoryPort,
        as2_partnerships: AS2PartnershipRepositoryPort,
        webhooks: WebhookRepositoryPort,
        edi_headers: EdiHeaderRepositoryPort,
    ) -> None:
        super().__init__(tenant_session)
        self.edi_messages = edi_messages
        self.edi_jsons = edi_jsons
        self.api_gateway_receipts = api_gateway_receipts
        self.traces = traces
        self.outbox = outbox
        self.inbound_routes = inbound_routes
        self.outbound_routes = outbound_routes
        self.sftp_partners = sftp_partners
        self.as2_partners = as2_partners
        self.as2_partnerships = as2_partnerships
        self.webhooks = webhooks
        self.edi_headers = edi_headers

    async def record_idempotency(self, tenant_id: str, idempotency_key: str) -> bool:
        """
        Attempts to insert an idempotency record into the events_processed table.
        Returns True if successful (meaning the event is new).
        Returns False if a unique constraint violation occurs (meaning the event was already processed).
        This executes within the UoW's active transaction but does NOT commit.
        """
        if not tenant_id or not idempotency_key:
            return True

        stmt = (
            insert(ProcessedEvent)
            .values(tenant_id=tenant_id, idempotency_key=idempotency_key)
            .on_conflict_do_nothing(index_elements=["tenant_id", "idempotency_key"])
        )
        result = await self.session.execute(stmt)
        return type(result) is CursorResult and result.rowcount > 0

    async def has_been_processed(self, tenant_id: str, idempotency_key: str) -> bool:
        """
        Checks if an idempotency record exists in the events_processed table.
        """
        if not tenant_id or not idempotency_key:
            return False

        stmt = select(ProcessedEvent).where(
            ProcessedEvent.tenant_id == tenant_id,
            ProcessedEvent.idempotency_key == idempotency_key,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None
