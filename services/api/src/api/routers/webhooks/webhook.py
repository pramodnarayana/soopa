from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from identity.dependencies import get_current_tenant_id

from api.adapters.http.dtos import (
    CreateWebhookRequest,
    PartnerResponse,
)
from api.core.provisioning import ProvisioningService
from api.core.uow import UnitOfWork
from api.dependencies import get_tenant_uow
from api.domain.models import CreateWebhookCmd

router = APIRouter(prefix="/webhook", tags=["Webhooks"])


@router.post("", response_model=PartnerResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    request: CreateWebhookRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """Creates a new Webhook delivery destination for this tenant."""
    async with uow:
        service = ProvisioningService(tenant_repo=uow.data_plane, global_repo=uow.control_plane)

        cmd = CreateWebhookCmd(
            name=request.name,
            url=str(request.url),
            auth_header_vault_ref=request.auth_header_vault_ref,
        )

        _ = await service.create_webhook(tenant_id, cmd)
        await uow.commit()

        async with uow:
            if not uow.control_plane:
                raise HTTPException(status_code=500, detail="Control plane not initialized")
            partner = await uow.control_plane.get_webhook(tenant_id, _.partner_id)
            if not partner or partner.tenant_id != tenant_id:
                raise HTTPException(status_code=404, detail="Webhook not found after creation")

        return PartnerResponse(
            partner_id=partner.id,
            tenant_id=tenant_id,
            name=partner.name,
            type="WEBHOOK",
            status="ACTIVE" if partner.active else "INACTIVE",
            active=partner.active,
            url=partner.url,
        )
