from identity.domain.identity_context import PLATFORM_TENANT_ID

from unified_api.adapters.inbound.http.dependencies.edi.auth import get_current_tenant_id
from unified_api.adapters.inbound.http.dependencies.edi.database import get_control_plane_uow

"""
Trading Partners router package.

Trading Partners are business entities this platform exchanges EDI documents with.
Each module handles a specific transport protocol:
  - as2.py   — AS2 protocol (HTTPS + digital signatures)
  - sftp.py  — SFTP protocol (SSH file transfer)
"""

from typing import Any

from edi.adapters.outbound.database.uow_adapter import (
    SqlAlchemyControlPlaneUnitOfWork as ControlPlaneUnitOfWork,
)
from fastapi import APIRouter, Depends

from unified_api.adapters.inbound.http.dtos.edi.dtos import (
    PartnerResponse,
    TradingPartnerStatusResponse,
)
from unified_api.adapters.inbound.http.routers.edi.trading_partners import as2, sftp

_PREFIX = "/api/v1/tenants/{tenant_id}/edi/trading-partners"

router = APIRouter(prefix=_PREFIX)


@router.get("", response_model=list[PartnerResponse])
async def list_trading_partners(
    tenant_id: str = Depends(get_current_tenant_id),
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> Any:
    """Lists all tenant trading partners (AS2 and SFTP)."""
    async with uow:
        # AS2 partners are global platform entities (tenant_id = PLATFORM_TENANT_ID) or tenant-specific
        as2_partners = list(await uow.as2_partners.list_as2_partners(tenant_id))
        if tenant_id != PLATFORM_TENANT_ID:
            as2_partners_global = await uow.as2_partners.list_as2_partners(PLATFORM_TENANT_ID)
            as2_partners = as2_partners + list(as2_partners_global)

        sftp_partners = await uow.sftp_partners.list_sftp_partners(tenant_id)

        partners = []
        for p in as2_partners:
            partners.append(
                PartnerResponse(
                    partner_id=p.id,
                    tenant_id=p.tenant_id or "",
                    name=p.name,
                    type="AS2",
                    status=TradingPartnerStatusResponse.ACTIVE
                    if p.active
                    else TradingPartnerStatusResponse.INACTIVE,
                    active=p.active,
                    as2_id=p.as2_id,
                    is_local=p.is_local,
                    url=str(p.url) if p.url else None,
                )
            )
        for sp in sftp_partners:
            partners.append(
                PartnerResponse(
                    partner_id=sp.id,
                    tenant_id=sp.tenant_id,
                    name=sp.name,
                    type="SFTP",
                    status=TradingPartnerStatusResponse.ACTIVE
                    if sp.active
                    else TradingPartnerStatusResponse.INACTIVE,
                    active=sp.active,
                    host=sp.host,
                    port=sp.port,
                    username=sp.username,
                    inbound_remote_path=sp.inbound_remote_path,
                    outbound_remote_path=sp.outbound_remote_path,
                )
            )

        return partners


router.include_router(as2.router)
router.include_router(sftp.router)
