import structlog

from edi.domain.constants import TransactionDirection
from edi.domain.models import ConnectionType, InboundRouteDomainModel
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class ListInboundRoutesUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def list_inbound_routes(self, tenant_id: str) -> list[InboundRouteDomainModel]:
        inbound = await self.uow.inbound_routes.list_inbound_routes(tenant_id)

        as2_ids: set[str] = set()
        sftp_ids: set[str] = set()
        webhook_ids: set[str] = set()

        for r in inbound:
            if r.as2_partner_id:
                as2_ids.add(r.as2_partner_id)
            if r.sftp_partner_id:
                sftp_ids.add(r.sftp_partner_id)
            if r.webhook_id:
                webhook_ids.add(r.webhook_id)

        as2_names = (
            await self.uow.as2_partners.get_as2_partners_by_ids(tenant_id, list(as2_ids))
            if as2_ids
            else {}
        )
        sftp_names = (
            await self.uow.sftp_partners.get_sftp_partners_by_ids(tenant_id, list(sftp_ids))
            if sftp_ids
            else {}
        )
        webhook_names: dict[str, str] = {}

        results: list[InboundRouteDomainModel] = []

        def _resolve_destination(r: InboundRouteDomainModel) -> tuple[ConnectionType | str, str]:
            if r.as2_partner_id:
                return ConnectionType.AS2, as2_names.get(r.as2_partner_id, str(r.as2_partner_id))
            if r.sftp_partner_id:
                return ConnectionType.SFTP, sftp_names.get(
                    r.sftp_partner_id, str(r.sftp_partner_id)
                )
            if r.webhook_id:
                # Use a persisted route display name (r.name) as fallback, then ID
                display_name = webhook_names.get(r.webhook_id) or r.name or str(r.webhook_id)
                return ConnectionType.WEBHOOK, display_name
            return ConnectionType.UNKNOWN, ConnectionType.UNKNOWN.value

        for r in inbound:
            _dest_type, _dest_name = _resolve_destination(r)

            results.append(
                InboundRouteDomainModel(
                    id=r.id,
                    tenant_id=tenant_id,
                    name=r.name,
                    isa_sender_id=r.isa_sender_id,
                    isa_receiver_id=r.isa_receiver_id,
                    active=r.active,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                    trading_partner_id=r.trading_partner_id,
                    gs_sender_id=r.gs_sender_id,
                    gs_receiver_id=r.gs_receiver_id,
                    transaction_type=r.transaction_type,
                    webhook_id=str(r.webhook_id) if r.webhook_id else None,
                    as2_partner_id=str(r.as2_partner_id) if r.as2_partner_id else None,
                    sftp_partner_id=str(r.sftp_partner_id) if r.sftp_partner_id else None,
                    direction=TransactionDirection.INBOUND.value,
                    destination_name=_dest_name,
                )
            )

        return results
