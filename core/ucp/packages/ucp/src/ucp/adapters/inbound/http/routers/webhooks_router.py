from typing import Annotated, Any

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Header, HTTPException, status
from identity.domain.identity_context import IdentityContext
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.adapters.inbound.http.dtos.webhook_dtos import (
    CreateWebhookRequest,
    UpdateWebhookRequest,
    WebhookResponse,
)
from ucp.adapters.inbound.http.guards.tenant_auth_guard import require_tenant_member
from ucp.application.use_cases.webhooks import (
    CreateWebhookUseCase,
    DeleteWebhookUseCase,
    ListWebhooksUseCase,
    UpdateWebhookUseCase,
)
from ucp.bootstrap.container import Container
from ucp.core.container import get_db_session

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/webhooks", tags=["Webhooks"])


def _webhook_response(webhook: Any, tenant_id: str) -> WebhookResponse:
    """Shared mapper from ORM Webhook record to WebhookResponse DTO."""
    return WebhookResponse(
        webhook_id=webhook.id,
        tenant_id=tenant_id,
        name=webhook.name,
        active=webhook.active,
        url=str(webhook.url) if webhook.url else None,
    )


@router.get("", response_model=list[WebhookResponse], status_code=status.HTTP_200_OK)
@inject
async def list_webhooks(
    tenant_id: str,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    session: AsyncSession = Depends(get_db_session),
    use_case_factory: Any = Depends(Provide[Container.list_webhooks_use_case.provider]),
) -> Any:
    """Lists all configured webhook delivery destinations for this tenant."""
    use_case: ListWebhooksUseCase = use_case_factory(uow__session=session)
    webhooks = await use_case.execute(tenant_id)
    return [_webhook_response(p, tenant_id) for p in webhooks]


@router.post("", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
@inject
async def create_webhook(
    tenant_id: str,
    request: CreateWebhookRequest,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    session: AsyncSession = Depends(get_db_session),
    use_case_factory: Any = Depends(Provide[Container.create_webhook_use_case.provider]),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> Any:
    """Creates a new webhook destination."""
    use_case: CreateWebhookUseCase = use_case_factory(uow__session=session)
    webhook = await use_case.execute(
        tenant_id=tenant_id,
        name=request.name,
        url=str(request.url),
        auth_header_vault_ref=request.auth_header_vault_ref,
        idempotency_key=idempotency_key,
    )
    return _webhook_response(webhook, tenant_id)


@router.patch("/{webhook_id}", response_model=WebhookResponse, status_code=status.HTTP_200_OK)
@inject
async def update_webhook(
    tenant_id: str,
    webhook_id: str,
    request: UpdateWebhookRequest,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    session: AsyncSession = Depends(get_db_session),
    use_case_factory: Any = Depends(Provide[Container.update_webhook_use_case.provider]),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> Any:
    """Updates an existing webhook destination."""
    try:
        use_case: UpdateWebhookUseCase = use_case_factory(uow__session=session)
        webhook = await use_case.execute(
            tenant_id=tenant_id,
            webhook_id=webhook_id,
            name=request.name,
            url=str(request.url) if request.url else None,
            active=request.active,
            idempotency_key=idempotency_key,
        )
        return _webhook_response(webhook, tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_webhook(
    tenant_id: str,
    webhook_id: str,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    session: AsyncSession = Depends(get_db_session),
    use_case_factory: Any = Depends(Provide[Container.delete_webhook_use_case.provider]),
) -> None:
    """Deletes a webhook destination."""
    try:
        use_case: DeleteWebhookUseCase = use_case_factory(uow__session=session)
        await use_case.execute(tenant_id=tenant_id, webhook_id=webhook_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
