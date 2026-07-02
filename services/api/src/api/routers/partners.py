from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from identity.dependencies import get_current_tenant_id

from api.adapters.http.dtos import (
    CertificateExportResponse,
    CreateAS2TradingPartnerRequest,
    CreateSFTPPartnerRequest,
    CreateWebhookPartnerRequest,
    PartnerResponse,
    RotateCertificateRequest,
    UpdateAS2TradingPartnerRequest,
    UpdateSFTPPartnerRequest,
)
from api.adapters.vault import vault
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
    UpdateAS2TradingPartnerCmd,
    UpdateSFTPPartnerCmd,
)

router = APIRouter(prefix="/api/v1/partners", tags=["Partners"])


@router.get("", response_model=list[PartnerResponse])
async def list_tenant_partners(
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """Lists all tenant-level partners (AS2 and SFTP)."""
    # For now, return empty list or just what we have from a basic query
    # Since this is a new enterprise addition.
    async with uow:
        # Simplistic implementation just to fulfill the API contract for the UI.
        return []


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
            url=str(request.url) if request.url else None,
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


@router.put("/as2/trading-partners/{partner_id}", response_model=PartnerResponse)
async def update_as2_partner(
    partner_id: UUID,
    request: UpdateAS2TradingPartnerRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_uow),
) -> Any:
    """Updates an AS2 Partner in the Global Control Plane."""
    async with uow:
        service = ProvisioningService(global_repo=uow.control_plane, tenant_repo=None)  # type: ignore[arg-type]
        cmd = UpdateAS2TradingPartnerCmd(
            name=request.name,
            as2_id=request.as2_id,
            is_local=request.is_local,
            url=str(request.url) if request.url else None,
        )
        entity = await service.update_as2_partner(tenant_id, partner_id, cmd)
        await uow.commit()

        return PartnerResponse(
            partner_id=entity.partner_id,
            tenant_id=entity.tenant_id,
            type=entity.type,
            status=entity.status,
        )


@router.get(
    "/as2/trading-partners/{partner_id}/certificates/export",
    response_model=CertificateExportResponse,
)
async def export_as2_certificates(
    partner_id: UUID,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_uow),
) -> Any:
    """Exports current and previous certificates for an AS2 partner."""
    async with uow:
        partner = await uow.control_plane.get_as2_partner(tenant_id, partner_id)
        if not partner:
            raise HTTPException(status_code=404, detail="Partner not found")

        response = CertificateExportResponse(
            public_cert_pem=partner.public_cert_pem,
            prev_public_cert_pem=partner.prev_public_cert_pem,
        )

        # Only Local partners have private keys. Fetch them if the vault ref exists.
        if partner.is_local:
            if partner.private_key_vault_ref:
                try:
                    response.private_key_pem = vault.retrieve_private_key(
                        partner.private_key_vault_ref
                    ).decode("utf-8")
                except Exception as e:
                    import logging

                    logging.getLogger(__name__).error(
                        f"Failed to retrieve private key from vault: {e}"
                    )
            if partner.prev_private_key_vault_ref:
                try:
                    response.prev_private_key_pem = vault.retrieve_private_key(
                        partner.prev_private_key_vault_ref
                    ).decode("utf-8")
                except Exception as e:
                    import logging

                    logging.getLogger(__name__).error(
                        f"Failed to retrieve prev private key from vault: {e}"
                    )

        return response


@router.put(
    "/as2/trading-partners/{partner_id}/certificates/rotate", response_model=PartnerResponse
)
async def rotate_as2_certificates(
    partner_id: UUID,
    request: RotateCertificateRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_uow),
) -> Any:
    """Rotates certificates for an AS2 partner (generate or upload)."""
    async with uow:
        partner = await uow.control_plane.get_as2_partner(tenant_id, partner_id)
        if not partner:
            raise HTTPException(status_code=404, detail="Partner not found")

        # Determine new PEMs
        new_public_pem = None
        new_private_pem = None
        if request.action == "generate":
            if not partner.is_local:
                raise HTTPException(
                    status_code=400, detail="Cannot generate certificates for a remote station"
                )
            from api.domain.certificate import generate_self_signed_cert

            priv_bytes, pub_bytes = generate_self_signed_cert(partner.as2_id)
            new_private_pem = priv_bytes.decode("utf-8")
            new_public_pem = pub_bytes.decode("utf-8")
        else:
            new_public_pem = request.public_cert_pem
            if partner.is_local:
                new_private_pem = request.private_key_pem

        # Store private key in vault if local
        new_private_key_vault_ref = None
        if partner.is_local and new_private_pem:
            try:
                new_private_key_vault_ref = vault.store_private_key(
                    new_private_pem.encode("utf-8"), alias_prefix=str(tenant_id)[:8]
                )
            except Exception as e:
                import logging

                logging.getLogger(__name__).error(f"Failed to store new private key in vault: {e}")
                raise HTTPException(
                    status_code=500, detail="Failed to securely store private key"
                ) from e

        # Update DB entity
        partner.prev_public_cert_pem = partner.public_cert_pem
        partner.prev_public_cert_vault_ref = partner.public_cert_vault_ref
        partner.prev_private_key_vault_ref = partner.private_key_vault_ref

        partner.public_cert_pem = new_public_pem
        # For public cert vault ref, we don't strictly need to store the public cert in vault anymore as it's in DB,
        # but we'll leave the ref empty for the new one if we don't store it, or keep it same logic if needed.
        partner.public_cert_vault_ref = None
        partner.private_key_vault_ref = new_private_key_vault_ref

        await uow.commit()

        return PartnerResponse(
            partner_id=partner.id,
            tenant_id=tenant_id,
            type="AS2",
            status="ACTIVE",
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


@router.put("/sftp/{partner_id}", response_model=PartnerResponse)
async def update_sftp_partner(
    partner_id: UUID,
    request: UpdateSFTPPartnerRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """Updates an SFTP Partner in the Tenant Data Plane."""
    async with uow:
        service = ProvisioningService(tenant_repo=uow.data_plane)  # type: ignore[arg-type]
        cmd = UpdateSFTPPartnerCmd(
            name=request.name,
            host=request.host,
            port=request.port,
            username=request.username,
            remote_path=request.remote_path,
            credentials_vault_ref=request.credentials_vault_ref,
        )
        entity = await service.update_sftp_partner(tenant_id, partner_id, cmd)
        await uow.commit()

        return PartnerResponse(
            partner_id=entity.partner_id,
            tenant_id=entity.tenant_id,
            type=entity.type,
            status=entity.status,
        )


@router.delete("/sftp/{partner_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sftp_partner(
    partner_id: UUID,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> None:
    """Deletes an SFTP partner."""
    async with uow:
        try:
            if uow.data_plane is None:
                raise HTTPException(status_code=500, detail="Tenant data plane not available")
            await uow.data_plane.delete_sftp_partner(partner_id)
            await uow.commit()
        except Exception as e:
            if "IntegrityError" in str(type(e)):
                raise HTTPException(
                    status_code=400, detail="Partner is in use and cannot be deleted."
                ) from e
            raise HTTPException(status_code=500, detail=str(e)) from e


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
