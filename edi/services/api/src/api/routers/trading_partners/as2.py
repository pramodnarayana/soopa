import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from identity.dependencies import get_current_tenant_id, get_raw_jwt

from api.adapters.http.dtos import (
    AS2TradingPartnerResponse,
    CertificateExportResponse,
    RotateCertificateRequest,
)
from api.core.services import AS2PartnerService
from api.core.uow import UnitOfWork
from api.dependencies import get_current_user_profile, get_uow, get_vault
from api.domain.certificate import generate_self_signed_cert
from api.ports.vault import VaultPort

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Partners — AS2"])


@router.get(
    "/as2/{partner_id}/certificates/export",
    response_model=CertificateExportResponse,
)
async def export_as2_certificates(
    partner_id: UUID,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_uow),
    token_payload: dict[str, Any] = Depends(get_raw_jwt),
    profile: dict[str, Any] = Depends(get_current_user_profile),
    vault: VaultPort = Depends(get_vault),
) -> Any:
    """Exports current and previous certificates for an AS2 partner."""
    async with uow:
        partner = await uow.as2_partners.get_as2_partner(tenant_id, partner_id)
        if not partner:
            partner = await uow.as2_partners.get_as2_partner(0, partner_id)
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
                except Exception as e:
                    logger.error(f"Failed to retrieve private key from vault: {e}", exc_info=True)
                    raise HTTPException(
                        status_code=500, detail="Failed to retrieve private key from vault"
                    ) from e

            if partner.prev_private_key_vault_ref:
                try:
                    response.prev_private_key_pem = vault.retrieve_private_key(
                        partner.prev_private_key_vault_ref
                    ).decode("utf-8")
                except Exception as e:
                    logger.error(
                        f"Failed to retrieve prev private key from vault: {e}", exc_info=True
                    )
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to retrieve prev private key from vault",
                    ) from e

        return response


@router.put(
    "/as2/{partner_id}/certificates/rotate",
    response_model=AS2TradingPartnerResponse,
)
async def rotate_as2_certificates(
    partner_id: UUID,
    request: RotateCertificateRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_uow),
    profile: dict[str, Any] = Depends(get_current_user_profile),
    vault: VaultPort = Depends(get_vault),
) -> Any:
    """Rotates certificates for an AS2 partner."""
    async with uow:
        partner = await uow.as2_partners.get_as2_partner(tenant_id, partner_id)
        if not partner:
            partner = await uow.as2_partners.get_as2_partner(0, partner_id)
        if not partner:
            raise HTTPException(status_code=404, detail="Partner not found")

        actual_tenant_id = partner.tenant_id
        assert actual_tenant_id is not None

        if partner.is_local and "certificates:rotate" not in profile["permissions"]:
            raise HTTPException(
                status_code=403, detail="Insufficient permissions to rotate certificates."
            )

        public_cert_pem = request.public_cert_pem
        private_key_vault_ref = None

        if partner.is_local:
            if request.action == "generate":
                private_key_bytes, public_cert_bytes = generate_self_signed_cert(
                    common_name=partner.as2_id
                )
                private_key_vault_ref = vault.store_private_key(
                    private_key_pem=private_key_bytes,
                    alias_prefix=f"{partner.name.replace(' ', '_').lower()}_rotated",
                )
                public_cert_pem = public_cert_bytes.decode("utf-8")
            elif request.action == "upload":
                if not request.private_key_pem or not request.public_cert_pem:
                    raise HTTPException(
                        status_code=400,
                        detail="Both public_cert_pem and private_key_pem required for upload.",
                    )
                private_key_vault_ref = vault.store_private_key(
                    private_key_pem=request.private_key_pem.encode("utf-8"),
                    alias_prefix=f"{partner.name.replace(' ', '_').lower()}_uploaded",
                )
        else:
            if not request.public_cert_pem:
                raise HTTPException(
                    status_code=400, detail="public_cert_pem required for remote partners."
                )

        try:
            svc = AS2PartnerService(uow=uow)
            updated_partner = await svc.rotate_certificates(
                tenant_id=actual_tenant_id,
                partner_id=partner_id,
                new_public_cert=str(public_cert_pem),
                new_private_key_vault_ref=private_key_vault_ref,
            )
            await uow.commit()
        except ValueError as e:
            if private_key_vault_ref:
                vault.delete_secret(private_key_vault_ref)
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            if private_key_vault_ref:
                vault.delete_secret(private_key_vault_ref)
            raise HTTPException(status_code=500, detail="Internal server error") from e

        return AS2TradingPartnerResponse(
            id=str(updated_partner.partner_id),
            name=updated_partner.name,
            as2_id=partner.as2_id,
            is_local=partner.is_local,
            url=partner.url,
            active=updated_partner.status == "ACTIVE",
        )
