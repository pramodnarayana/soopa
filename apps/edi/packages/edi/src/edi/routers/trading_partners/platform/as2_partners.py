from typing import Any

from config.settings import get_settings
from fastapi import APIRouter, Depends, HTTPException, status
from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy.exc import IntegrityError

from edi.adapters.http.dtos import (
    AS2TradingPartnerResponse,
    CreateAS2TradingPartnerRequest,
    GenerateCertRequest,
    GenerateCertResponse,
    RotateCertificateRequest,
    UpdateAS2TradingPartnerRequest,
)
from edi.adapters.uow_adapter import SqlAlchemyControlPlaneUnitOfWork as ControlPlaneUnitOfWork
from edi.core.exceptions import IdempotencyConflictError, OrchestrationError
from edi.core.services import AS2PartnerService
from edi.dependencies.auth import get_platform_user_profile
from edi.dependencies.database import get_control_plane_uow
from edi.dependencies.headers import get_idempotency_key
from edi.dependencies.services import get_vault
from edi.domain.certificate import generate_self_signed_cert
from edi.domain.models import (
    CreateAS2TradingPartnerCmd,
    RotateAS2CertificateCmd,
    UpdateAS2TradingPartnerCmd,
)
from edi.ports.vault import VaultPort

router = APIRouter(tags=["Platform Partners - AS2"])


@router.post(
    "/as2/certificates/generate",
    response_model=GenerateCertResponse,
    status_code=status.HTTP_200_OK,
)
async def generate_certificate(
    request: GenerateCertRequest,
    vault: VaultPort = Depends(get_vault),
) -> Any:
    """
    Generates a new self-signed AS2 certificate and stores the private key in Vault.
    Returns the public cert PEM and the vault reference for the private key.
    """
    private_key_bytes, public_cert_bytes = generate_self_signed_cert(common_name=request.as2_id)

    private_key_vault_ref = vault.store_private_key(
        private_key_pem=private_key_bytes,
        alias_prefix=request.as2_id.replace(" ", "_").lower(),
    )

    return GenerateCertResponse(
        public_cert_pem=public_cert_bytes.decode("utf-8"),
        private_key_vault_ref=private_key_vault_ref,
    )


import logging

from edi.adapters.http.dtos import CertificateExportResponse

logger = logging.getLogger(__name__)


@router.put(
    "/as2/certificates/{partner_id}/rotate",
    response_model=AS2TradingPartnerResponse,
)
async def rotate_platform_as2_certificates(
    partner_id: str,
    request: RotateCertificateRequest,
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
    profile: dict[str, Any] = Depends(get_platform_user_profile),
    vault: VaultPort = Depends(get_vault),
) -> Any:
    """Rotates certificates for a Platform AS2 partner."""
    async with uow:
        partner = await uow.as2_partners.get_as2_partner(PLATFORM_TENANT_ID, partner_id)
        if not partner:
            raise HTTPException(status_code=404, detail="Partner not found")

        if partner.is_local and "certificates:rotate" not in profile["permissions"]:
            raise HTTPException(
                status_code=403, detail="Insufficient permissions to rotate certificates."
            )

        cmd = RotateAS2CertificateCmd(
            action=request.action,
            public_cert_pem=request.public_cert_pem,
            private_key_pem=request.private_key_pem,
        )

        try:
            svc = AS2PartnerService(uow=uow)
            updated_partner = await svc.rotate_certificates(
                tenant_id=PLATFORM_TENANT_ID,
                partner_id=partner_id,
                cmd=cmd,
                vault=vault,
            )
            await uow.commit()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail="Internal server error") from e

        return AS2TradingPartnerResponse(
            id=str(updated_partner.partner_id),
            name=updated_partner.name,
            as2_id=partner.as2_id,
            is_local=partner.is_local,
            url=partner.url,
            active=updated_partner.status == "ACTIVE",
        )


@router.get(
    "/as2/certificates/{partner_id}/export",
    response_model=CertificateExportResponse,
)
async def export_platform_as2_certificates(
    partner_id: str,
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
    idempotency_key: str | None = Depends(get_idempotency_key),
    profile: dict[str, Any] = Depends(get_platform_user_profile),
    vault: VaultPort = Depends(get_vault),
) -> Any:
    """Exports current and previous certificates for a Platform AS2 partner."""
    async with uow:
        partner = await uow.as2_partners.get_as2_partner(
            tenant_id=PLATFORM_TENANT_ID, partner_id=partner_id
        )
        if not partner:
            raise HTTPException(status_code=404, detail="Partner not found")

        response = CertificateExportResponse(
            public_cert_pem=partner.public_cert_pem,
            prev_public_cert_pem=partner.prev_public_cert_pem,
        )

        if partner.is_local:
            if "certificates:export_private" not in profile["permissions"]:
                raise HTTPException(
                    status_code=403, detail="Insufficient permissions to export private keys."
                )

            if partner.private_key_vault_ref:
                try:
                    response.private_key_pem = vault.retrieve_private_key(
                        partner.private_key_vault_ref
                    ).decode("utf-8")
                except OrchestrationError as e:
                    logger.exception("Failed to retrieve private key from vault")
                    raise HTTPException(
                        status_code=500, detail="Failed to retrieve private key from vault"
                    ) from e

            if partner.prev_private_key_vault_ref:
                try:
                    response.prev_private_key_pem = vault.retrieve_private_key(
                        partner.prev_private_key_vault_ref
                    ).decode("utf-8")
                except OrchestrationError as e:
                    logger.exception("Failed to retrieve prev private key from vault")
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to retrieve prev private key from vault",
                    ) from e

        return response


@router.delete(
    "/as2/certificates/secret",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_certificate_secret(
    vault_ref: str,
    vault: VaultPort = Depends(get_vault),
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> None:
    """Deletes an orphaned private key from Vault if the UI discards it before saving."""
    async with uow:
        in_use = await uow.as2_partners.is_vault_ref_in_use(vault_ref)
        if in_use:
            raise HTTPException(
                status_code=400, detail="Cannot delete a private key that is currently in use."
            )

    vault.delete_secret(vault_ref)


@router.post(
    "/as2/trading-partners",
    response_model=AS2TradingPartnerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_platform_as2_partner(
    request: CreateAS2TradingPartnerRequest,
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
    idempotency_key: str | None = Depends(get_idempotency_key),
    vault: VaultPort = Depends(get_vault),
    _: Any = Depends(get_platform_user_profile),
) -> Any:
    """
    Creates a new Global AS2 Trading Partner (Local or Remote) in the Control Plane.
    If is_local is True, automatically generates a self-signed cert and stores private key in Vault.
    """
    logger.info(
        "[create_as2_partner] START name=%r as2_id=%r is_local=%r has_idempotency_key=%r",
        request.name,
        request.as2_id,
        request.is_local,
        bool(idempotency_key),
    )
    public_cert_pem = request.public_cert_pem
    private_key_vault_ref = request.private_key_vault_ref
    auto_generated = False
    commit_success = False

    try:
        async with uow:
            svc = AS2PartnerService(uow=uow)
            if idempotency_key:
                fingerprint_data = {
                    "tenant_id": str(PLATFORM_TENANT_ID),
                    "name": request.name,
                    "as2_id": request.as2_id,
                    "is_local": request.is_local,
                    "url": str(request.url) if request.url else None,
                    "public_cert_pem": request.public_cert_pem,
                    "public_cert_vault_ref": request.public_cert_vault_ref,
                }
                existing_partner = await svc.check_and_reserve_idempotency(
                    tenant_id=PLATFORM_TENANT_ID,
                    request_data=fingerprint_data,
                    idempotency_key=idempotency_key,
                )
                if existing_partner:
                    p = await uow.as2_partners.get_as2_partner(
                        PLATFORM_TENANT_ID, existing_partner.partner_id
                    )
                    if p:
                        return AS2TradingPartnerResponse(
                            id=str(p.id),
                            name=p.name,
                            as2_id=p.as2_id,
                            is_local=p.is_local,
                            url=p.url,
                            active=p.active,
                        )

            if request.is_local:
                if private_key_vault_ref:
                    pass  # Pre-stored vault ref
                elif request.private_key_pem:
                    auto_generated = True
                    private_key_vault_ref = vault.store_private_key(
                        private_key_pem=request.private_key_pem.encode(),
                        alias_prefix=request.name.replace(" ", "_").lower(),
                    )
                else:
                    auto_generated = True
                    private_key_bytes, public_cert_bytes = generate_self_signed_cert(
                        common_name=request.as2_id
                    )
                    private_key_vault_ref = vault.store_private_key(
                        private_key_pem=private_key_bytes,
                        alias_prefix=request.name.replace(" ", "_").lower(),
                    )
                    public_cert_pem = public_cert_bytes.decode("utf-8")

            url = str(request.url) if request.url else None
            if request.is_local and not url:
                settings = get_settings()
                url = f"{settings.public.base_url}/api/v1/as2/receive"

            cmd = CreateAS2TradingPartnerCmd(
                name=request.name,
                as2_id=request.as2_id,
                is_local=request.is_local,
                url=url,
                public_cert_pem=public_cert_pem,
                public_cert_vault_ref=request.public_cert_vault_ref,
                private_key_vault_ref=private_key_vault_ref,
            )

            entity = await svc.create_as2_partner(
                tenant_id=PLATFORM_TENANT_ID,
                cmd=cmd,
                idempotency_key=idempotency_key,
            )
            await uow.commit()
            commit_success = True

            p = await uow.as2_partners.get_as2_partner(
                tenant_id=PLATFORM_TENANT_ID, partner_id=entity.partner_id
            )
            if not p:
                raise HTTPException(status_code=500, detail="Partner creation failed")

            return AS2TradingPartnerResponse(
                id=str(p.id),
                name=p.name,
                as2_id=p.as2_id,
                is_local=p.is_local,
                url=p.url,
                active=p.active,
            )
    except IdempotencyConflictError as e:
        if auto_generated and private_key_vault_ref and not commit_success:
            vault.delete_secret(private_key_vault_ref)
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        if auto_generated and private_key_vault_ref and not commit_success:
            vault.delete_secret(private_key_vault_ref)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except IntegrityError as e:
        if auto_generated and private_key_vault_ref and not commit_success:
            vault.delete_secret(private_key_vault_ref)
        constraint_name = ""
        if hasattr(e, "orig") and e.orig is not None:
            diag = getattr(e.orig, "diag", None)
            if diag is not None:
                constraint_name = str(getattr(diag, "constraint_name", e.orig))
            else:
                constraint_name = str(e.orig)
        if "uq_tenant_as2_id" in constraint_name:
            raise HTTPException(
                status_code=400, detail="AS2 ID already exists for this tenant."
            ) from e
        raise HTTPException(status_code=500, detail="Database integrity error") from e
    except OrchestrationError as e:
        if auto_generated and private_key_vault_ref and not commit_success:
            vault.delete_secret(private_key_vault_ref)
        raise OrchestrationError("Failed to orchestrate AS2 partner creation") from e


@router.get("/as2/trading-partners", response_model=list[AS2TradingPartnerResponse])
async def list_platform_as2_partners(
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> Any:
    """
    Returns all global AS2 partners (tenant_id = 0).
    """
    async with uow:
        partners = await uow.as2_partners.list_as2_partners(tenant_id=PLATFORM_TENANT_ID)
        return [
            AS2TradingPartnerResponse(
                id=str(p.id),
                name=p.name,
                as2_id=p.as2_id,
                is_local=p.is_local,
                url=p.url,
                active=p.active,
            )
            for p in partners
        ]


@router.put("/as2/trading-partners/{partner_id}", response_model=AS2TradingPartnerResponse)
async def update_platform_as2_partner(
    partner_id: str,
    request: UpdateAS2TradingPartnerRequest,
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
    idempotency_key: str | None = Depends(get_idempotency_key),
) -> Any:
    """Updates a global AS2 partner."""
    async with uow:
        svc = AS2PartnerService(uow=uow)
        cmd = UpdateAS2TradingPartnerCmd(
            name=request.name,
            as2_id=request.as2_id,
            is_local=request.is_local,
            url=str(request.url) if request.url else None,
            active=request.active,
        )
        try:
            await svc.update_as2_partner(
                tenant_id=PLATFORM_TENANT_ID,
                partner_id=partner_id,
                cmd=cmd,
                idempotency_key=idempotency_key,
            )
            updated_partner = await uow.as2_partners.get_as2_partner(
                tenant_id=PLATFORM_TENANT_ID, partner_id=partner_id
            )
            if not updated_partner:
                raise HTTPException(status_code=404, detail="Partner not found after update")

            await uow.commit()
            return AS2TradingPartnerResponse(
                id=str(updated_partner.id),
                name=updated_partner.name,
                as2_id=updated_partner.as2_id,
                is_local=updated_partner.is_local,
                url=updated_partner.url,
                active=updated_partner.active,
            )
        except HTTPException:
            raise
        except OrchestrationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/as2/trading-partners/{partner_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_platform_as2_partner(
    partner_id: str,
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
    idempotency_key: str | None = Depends(get_idempotency_key),
) -> None:
    """Deletes an AS2 partner."""
    async with uow:
        svc = AS2PartnerService(uow=uow)
        try:
            await svc.delete_as2_partner(
                tenant_id=PLATFORM_TENANT_ID,
                partner_id=partner_id,
                idempotency_key=idempotency_key,
            )
            await uow.commit()
        except OrchestrationError as e:
            if "IntegrityError" in str(type(e)):
                raise HTTPException(
                    status_code=400, detail="Partner is in use and cannot be deleted."
                ) from e
            raise HTTPException(status_code=500, detail=str(e)) from e
