"""
Webhooks router package.

Webhooks are outbound HTTP push delivery channels — they describe
where processed EDI data is pushed to after the pipeline completes.
They are NOT trading partners; they are delivery destinations.
"""

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Depends
from identity.dependencies import get_current_tenant_id

from api.adapters.http.dtos import PartnerResponse
from api.core.uow import UnitOfWork
from api.dependencies import get_tenant_uow
from api.routers.webhooks import webhook

router = APIRouter(prefix="/api/v1/webhooks")


@router.get("", response_model=list[PartnerResponse])
async def list_webhooks(
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """Lists all configured webhook delivery destinations for this tenant."""
    async with uow:
        webhooks: Sequence[Any] = []
        if uow.control_plane:
            webhooks = await uow.control_plane.list_webhooks(tenant_id)

        return [
            PartnerResponse(
                partner_id=p.id,
                tenant_id=p.tenant_id,
                name=p.name,
                type="WEBHOOK",
                status="ACTIVE" if p.active else "INACTIVE",
                active=p.active,
            )
            for p in webhooks
        ]


router.include_router(webhook.router)
