import structlog

from edi.domain.enums import EdiDirection
from edi.domain.models.base import ConnectionType
from edi.domain.models.outbound_routes import OutboundRouteDomainModel
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class ListOutboundRoutesUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def execute(self, tenant_id: str) -> list[OutboundRouteDomainModel]:
        outbound = await self.uow.outbound_routes.list_outbound_routes(tenant_id)

        as2_ids: set[str] = set()
        sftp_ids: set[str] = set()

        for out_r in outbound:
            if out_r.as2_partner_id:
                as2_ids.add(out_r.as2_partner_id)
            if out_r.sftp_partner_id:
                sftp_ids.add(out_r.sftp_partner_id)

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

        results: list[OutboundRouteDomainModel] = []

        def _resolve_destination(r: OutboundRouteDomainModel) -> tuple[ConnectionType | str, str]:
            if r.as2_partner_id:
                return ConnectionType.AS2, as2_names.get(r.as2_partner_id, str(r.as2_partner_id))
            if r.sftp_partner_id:
                return ConnectionType.SFTP, sftp_names.get(
                    r.sftp_partner_id, str(r.sftp_partner_id)
                )
            return ConnectionType.UNKNOWN, ConnectionType.UNKNOWN.value

        for out_r in outbound:
            _dest_type, _dest_name = _resolve_destination(out_r)

            results.append(
                OutboundRouteDomainModel(
                    id=out_r.id,
                    tenant_id=tenant_id,
                    trading_partner_id=out_r.trading_partner_id,
                    name=out_r.name,
                    active=out_r.active,
                    created_at=out_r.created_at,
                    updated_at=out_r.updated_at,
                    as2_partner_id=str(out_r.as2_partner_id) if out_r.as2_partner_id else None,
                    sftp_partner_id=str(out_r.sftp_partner_id) if out_r.sftp_partner_id else None,
                    direction=EdiDirection.OUTBOUND,
                    destination_name=_dest_name,
                )
            )

        return results
