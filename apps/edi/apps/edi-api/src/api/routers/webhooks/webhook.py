"""
Webhooks router package.

Webhooks are outbound HTTP push delivery channels — they describe
where processed EDI data is pushed to after the pipeline completes.
They are NOT trading partners; they are delivery destinations.
"""

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.adapters.http.dtos import PartnerResponse
from api.core.uow import UnitOfWork
from api.dependencies.auth import get_current_tenant_id
from api.dependencies.database import get_tenant_uow

router = APIRouter(prefix="/api/v1/webhooks", tags=["Webhooks"])


def _partner_response(partner: Any, tenant_id: str) -> PartnerResponse:
    """Shared mapper from ORM Webhook record to PartnerResponse DTO."""
    return PartnerResponse(
        partner_id=partner.id,
        tenant_id=tenant_id,
        name=partner.name,
        type="WEBHOOK",
        status="ACTIVE" if partner.active else "INACTIVE",
        active=partner.active,
        url=str(partner.url) if partner.url else None,
    )


@router.get("", response_model=list[PartnerResponse])
async def list_webhooks(
    tenant_id: str = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """Lists all configured webhook delivery destinations for this tenant."""
    async with uow:
        if uow.global_session is None:
            raise HTTPException(status_code=500, detail="Control plane not initialized")
        webhooks: Sequence[Any] = await uow.webhooks.list_webhooks(tenant_id)
        return [_partner_response(p, tenant_id) for p in webhooks]
