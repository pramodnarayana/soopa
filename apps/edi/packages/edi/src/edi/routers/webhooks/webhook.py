"""
Webhooks router package.

Webhooks are outbound HTTP push delivery channels — they describe
where processed EDI data is pushed to after the pipeline completes.
They are NOT trading partners; they are delivery destinations.
"""

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException

from edi.adapters.http.dtos import CreateWebhookRequest, PartnerResponse, UpdateWebhookRequest
from edi.adapters.uow_adapter import SqlAlchemyControlPlaneUnitOfWork as ControlPlaneUnitOfWork
from edi.core.services.webhook_service import WebhookService
from edi.dependencies.auth import get_current_tenant_id
from edi.dependencies.database import get_control_plane_uow

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/edi/webhooks", tags=["Webhooks"])


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


def get_webhook_service(
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> WebhookService:
    return WebhookService(uow)


@router.get("", response_model=list[PartnerResponse])
async def list_webhooks(
    tenant_id: str = Depends(get_current_tenant_id),
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> Any:
    """Lists all configured webhook delivery destinations for this tenant."""
    async with uow:
        webhooks = await uow.webhooks.list_webhooks(tenant_id)
        return [_partner_response(p, tenant_id) for p in webhooks]


@router.post("", response_model=PartnerResponse)
async def create_webhook(
    request: CreateWebhookRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    service: WebhookService = Depends(get_webhook_service),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> Any:
    """Creates a new webhook destination."""
    async with service.uow:
        webhook = await service.create_webhook(
            tenant_id=tenant_id,
            name=request.name,
            url=str(request.url),
            auth_header_vault_ref=request.auth_header_vault_ref,
            idempotency_key=idempotency_key,
        )
        await service.uow.commit()
        return _partner_response(webhook, tenant_id)


@router.patch("/{webhook_id}", response_model=PartnerResponse)
async def update_webhook(
    webhook_id: str,
    request: UpdateWebhookRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    service: WebhookService = Depends(get_webhook_service),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> Any:
    """Updates an existing webhook destination."""
    async with service.uow:
        try:
            webhook = await service.update_webhook(
                tenant_id=tenant_id,
                webhook_id=webhook_id,
                name=request.name,
                url=str(request.url) if request.url else None,
                active=request.active,
                idempotency_key=idempotency_key,
            )
            await service.uow.commit()
            return _partner_response(webhook, tenant_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    service: WebhookService = Depends(get_webhook_service),
) -> None:
    """Deletes a webhook destination."""
    async with service.uow:
        try:
            await service.delete_webhook(tenant_id=tenant_id, webhook_id=webhook_id)
            await service.uow.commit()
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
