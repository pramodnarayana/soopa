"""
Webhooks router package.

Webhooks are outbound HTTP push delivery channels — they describe
where processed EDI data is pushed to after the pipeline completes.
They are NOT trading partners; they are delivery destinations.
"""

import ipaddress
import socket
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, HTTPException, status
from identity.dependencies import get_current_tenant_id

from api.adapters.http.dtos import CreateWebhookRequest, PartnerResponse, UpdateWebhookRequest
from api.core.services import WebhookService
from api.core.uow import UnitOfWork
from api.dependencies import get_tenant_uow
from api.domain.models import CreateWebhookCmd

router = APIRouter(prefix="/api/v1/webhooks", tags=["Webhooks"])


def _partner_response(partner: Any, tenant_id: int) -> PartnerResponse:
    """Shared mapper from ORM Webhook record to PartnerResponse DTO."""
    return PartnerResponse(
        partner_id=partner.id,
        tenant_id=tenant_id,
        name=partner.name,
        type="WEBHOOK",
        status="ACTIVE" if partner.active else "INACTIVE",
        active=partner.active,
        url=partner.url,
    )


async def _validate_webhook_url(url: str) -> None:
    try:
        parsed = urlparse(str(url))
        hostname = parsed.hostname
        if not hostname:
            raise ValueError("Invalid URL: no hostname")
        addr_info = await anyio.to_thread.run_sync(socket.getaddrinfo, hostname, None)
        for _, _, _, _, sockaddr in addr_info:
            ip = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip)
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_unspecified:
                raise HTTPException(status_code=400, detail="Webhook URL must be a public address")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid webhook URL") from e


@router.get("", response_model=list[PartnerResponse])
async def list_webhooks(
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """Lists all configured webhook delivery destinations for this tenant."""
    async with uow:
        if not uow.control_plane:
            raise HTTPException(status_code=500, detail="Control plane not initialized")
        webhooks: Sequence[Any] = await uow.control_plane.list_webhooks(tenant_id)
        return [_partner_response(p, tenant_id) for p in webhooks]


@router.post("", response_model=PartnerResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    request: CreateWebhookRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """Creates a new Webhook delivery destination for this tenant."""
    await _validate_webhook_url(str(request.url))

    async with uow:
        if not uow.control_plane:
            raise HTTPException(status_code=500, detail="Control plane not initialized")
        service = WebhookService(uow=uow)
        cmd = CreateWebhookCmd(
            name=request.name,
            url=str(request.url),
            auth_header_vault_ref=request.auth_header_vault_ref,
        )
        entity = await service.create_webhook(tenant_id, cmd)
        await uow.commit()

    # New session after commit — avoids nested session risk
    async with uow:
        if not uow.control_plane:
            raise HTTPException(status_code=500, detail="Control plane not initialized")
        partner = await uow.control_plane.get_webhook(tenant_id, entity.partner_id)
        if not partner or partner.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Webhook not found after creation")
        return _partner_response(partner, tenant_id)


@router.patch("/{webhook_id}", response_model=PartnerResponse)
async def update_webhook(
    webhook_id: UUID,
    request: UpdateWebhookRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """Updates name and/or active status of a Webhook delivery destination."""
    if request.url:
        await _validate_webhook_url(str(request.url))

    async with uow:
        if not uow.control_plane:
            raise HTTPException(status_code=500, detail="Control plane not initialized")
        service = WebhookService(uow=uow)
        success = await service.update_webhook(
            tenant_id,
            webhook_id,
            name=request.name,
            active=request.active,
            url=str(request.url) if request.url else None,
        )
        if not success:
            raise HTTPException(status_code=404, detail="Webhook not found")
        await uow.commit()

    # New session after commit
    async with uow:
        if not uow.control_plane:
            raise HTTPException(status_code=500, detail="Control plane not initialized")
        partner = await uow.control_plane.get_webhook(tenant_id, webhook_id)
        if not partner or partner.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Webhook not found")
        return _partner_response(partner, tenant_id)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: UUID,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> None:
    """Permanently deletes a Webhook."""
    async with uow:
        if not uow.control_plane:
            raise HTTPException(status_code=500, detail="Control plane not initialized")
        service = WebhookService(uow=uow)
        success = await service.delete_webhook(tenant_id, webhook_id)
        if not success:
            raise HTTPException(status_code=404, detail="Webhook not found")
        await uow.commit()
