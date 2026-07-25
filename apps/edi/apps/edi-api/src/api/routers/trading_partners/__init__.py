from api.dependencies.auth import get_current_tenant_id
from api.dependencies.database import get_tenant_uow

"""
Trading Partners router package.

Trading Partners are business entities this platform exchanges EDI documents with.
Each module handles a specific transport protocol:
  - as2.py   — AS2 protocol (HTTPS + digital signatures)
  - sftp.py  — SFTP protocol (SSH file transfer)
"""

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Depends

from api.adapters.http.dtos import PartnerResponse
from api.core.uow import UnitOfWork
from api.routers.trading_partners import as2, sftp

_PREFIX = "/api/v1/trading-partners"

router = APIRouter(prefix=_PREFIX)


@router.get("", response_model=list[PartnerResponse])
async def list_trading_partners(
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """Lists all tenant trading partners (AS2 and SFTP)."""
    async with uow:
        as2_partners: Sequence[Any] = []
        sftp_partners: Sequence[Any] = []
        if uow.global_session is not None:
            # AS2 partners are global platform entities (tenant_id = 0) or tenant-specific
            as2_partners = await uow.as2_partners.list_as2_partners(tenant_id)
            as2_partners_global = await uow.as2_partners.list_as2_partners(0)

            as2_partners = list(as2_partners) + list(as2_partners_global)

        sftp_partners = await uow.sftp_partners.list_sftp_partners(tenant_id)

        partners = []
        for p in as2_partners:
            partners.append(
                PartnerResponse(
                    partner_id=p.id,
                    tenant_id=p.tenant_id,
                    name=p.name,
                    type="AS2",
                    status="ACTIVE" if p.active else "INACTIVE",
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
                    status="ACTIVE" if sp.active else "INACTIVE",
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
