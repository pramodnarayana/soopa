from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from identity.dependencies import get_current_tenant_id

from api.adapters.http.dtos import (
    CreateAS2TradingPartnerRequest,
    CreateSFTPPartnerRequest,
    CreateWebhookPartnerRequest,
    PartnerResponse,
)
from api.core.provisioning import ProvisioningService
from api.core.uow import UnitOfWork
from api.dependencies import (
    get_tenant_uow,
    get_uow,
)
from api.domain.models import (
    CreateAS2TradingPartnerCmd,
    CreateSFTPPartnerCmd,
    CreateWebhookPartnerCmd,
)

router = APIRouter(prefix="/api/v1/partners", tags=["Partners"])


@router.post(
    "/as2/trading-partners", response_model=PartnerResponse, status_code=status.HTTP_201_CREATED
)
async def create_as2_partner(
    request: CreateAS2TradingPartnerRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_uow),
) -> Any:
    """
    Creates a new AS2 Partner in the Global Control Plane.
    Emits a provisioning event for workers to replicate this config to the Tenant Data Plane.
    """
    async with uow:
        # We ignore types here because data_plane is technically required, but
        # create_as2_partner only uses global_repo in its flow (with outbox pattern)
        service = ProvisioningService(global_repo=uow.control_plane, tenant_repo=None)  # type: ignore[arg-type]

        if not request.public_cert_pem and not request.public_cert_vault_ref:
            raise HTTPException(
                status_code=422,
                detail="Remote AS2 partners require a public certificate (PEM or Vault reference).",
            )

        cmd = CreateAS2TradingPartnerCmd(
            name=request.name,
            as2_id=request.as2_id,
            is_local=False,  # Tenant partners are usually remote
            public_cert_pem=request.public_cert_pem,
            public_cert_vault_ref=request.public_cert_vault_ref,
            private_key_vault_ref=None,  # Explicitly ignore
        )

        entity = await service.create_as2_partner(tenant_id, cmd)
        await uow.commit()

        return PartnerResponse(
            partner_id=entity.partner_id,
            tenant_id=entity.tenant_id,
            type=entity.type,
            status=entity.status,
        )


@router.post("/sftp", response_model=PartnerResponse, status_code=status.HTTP_201_CREATED)
async def create_sftp_partner(
    request: CreateSFTPPartnerRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """
    Creates a new SFTP Partner directly in the Tenant Data Plane.
    """
    async with uow:
        service = ProvisioningService(tenant_repo=uow.data_plane)  # type: ignore[arg-type]

        cmd = CreateSFTPPartnerCmd(
            name=request.name,
            host=request.host,
            port=request.port,
            username=request.username,
            remote_path=request.remote_path,
            credentials_vault_ref=request.credentials_vault_ref,
        )

        entity = await service.create_sftp_partner(tenant_id, cmd)
        await uow.commit()

        return PartnerResponse(
            partner_id=entity.partner_id,
            tenant_id=entity.tenant_id,
            type=entity.type,
            status=entity.status,
        )


@router.post("/webhook", response_model=PartnerResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook_partner(
    request: CreateWebhookPartnerRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """
    Creates a new Webhook Partner directly in the Tenant Data Plane.
    """
    async with uow:
        service = ProvisioningService(tenant_repo=uow.data_plane)  # type: ignore[arg-type]

        cmd = CreateWebhookPartnerCmd(
            name=request.name,
            url=str(request.url),
            auth_header_vault_ref=request.auth_header_vault_ref,
        )

        entity = await service.create_webhook_partner(tenant_id, cmd)
        await uow.commit()

        return PartnerResponse(
            partner_id=entity.partner_id,
            tenant_id=entity.tenant_id,
            type=entity.type,
            status=entity.status,
        )
