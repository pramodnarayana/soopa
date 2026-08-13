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
from edi.core.use_cases.webhooks import (
    CreateWebhookUseCase,
    DeleteWebhookUseCase,
    ListWebhooksUseCase,
    UpdateWebhookUseCase,
)
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


def get_create_webhook_use_case(
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> CreateWebhookUseCase:
    return CreateWebhookUseCase(uow)


def get_update_webhook_use_case(
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> UpdateWebhookUseCase:
    return UpdateWebhookUseCase(uow)


def get_delete_webhook_use_case(
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> DeleteWebhookUseCase:
    return DeleteWebhookUseCase(uow)


def get_list_webhooks_use_case(
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> ListWebhooksUseCase:
    return ListWebhooksUseCase(uow)


@router.get("", response_model=list[PartnerResponse])
async def list_webhooks(
    tenant_id: str = Depends(get_current_tenant_id),
    use_case: ListWebhooksUseCase = Depends(get_list_webhooks_use_case),
) -> Any:
    """Lists all configured webhook delivery destinations for this tenant."""
    webhooks = await use_case.execute(tenant_id)
    return [_partner_response(p, tenant_id) for p in webhooks]


@router.post("", response_model=PartnerResponse)
async def create_webhook(
    request: CreateWebhookRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    use_case: CreateWebhookUseCase = Depends(get_create_webhook_use_case),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> Any:
    """Creates a new webhook destination."""
    webhook = await use_case.execute(
        tenant_id=tenant_id,
        name=request.name,
        url=str(request.url),
        auth_header_vault_ref=request.auth_header_vault_ref,
        idempotency_key=idempotency_key,
    )
    return _partner_response(webhook, tenant_id)


@router.patch("/{webhook_id}", response_model=PartnerResponse)
async def update_webhook(
    webhook_id: str,
    request: UpdateWebhookRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    use_case: UpdateWebhookUseCase = Depends(get_update_webhook_use_case),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> Any:
    """Updates an existing webhook destination."""
    try:
        webhook = await use_case.execute(
            tenant_id=tenant_id,
            webhook_id=webhook_id,
            name=request.name,
            url=str(request.url) if request.url else None,
            active=request.active,
            idempotency_key=idempotency_key,
        )
        return _partner_response(webhook, tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    use_case: DeleteWebhookUseCase = Depends(get_delete_webhook_use_case),
) -> None:
    """Deletes a webhook destination."""
    try:
        await use_case.execute(tenant_id=tenant_id, webhook_id=webhook_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
