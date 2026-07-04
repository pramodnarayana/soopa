import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from identity.dependencies import get_current_tenant_id, get_raw_jwt

from api.adapters.http.dtos import CertificateExportResponse
from api.adapters.vault import vault
from api.core.uow import UnitOfWork
from api.dependencies import get_current_user_profile, get_uow

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Partners — AS2"])


@router.get(
    "/as2/trading-partners/{partner_id}/certificates/export",
    response_model=CertificateExportResponse,
)
async def export_as2_certificates(
    partner_id: UUID,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_uow),
    token_payload: dict[str, Any] = Depends(get_raw_jwt),
    profile: dict[str, Any] = Depends(get_current_user_profile),
) -> Any:
    """Exports current and previous certificates for an AS2 partner."""
    async with uow:
        partner = await uow.control_plane.get_as2_partner(tenant_id, partner_id)
        if not partner:
            partner = await uow.control_plane.get_as2_partner(0, partner_id)
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
                    logger.error(f"Failed to retrieve private key from vault: {e}")
                    raise HTTPException(
                        status_code=500, detail=f"Failed to retrieve private key from vault: {e}"
                    ) from e

            if partner.prev_private_key_vault_ref:
                try:
                    response.prev_private_key_pem = vault.retrieve_private_key(
                        partner.prev_private_key_vault_ref
                    ).decode("utf-8")
                except Exception as e:
                    logger.error(f"Failed to retrieve prev private key from vault: {e}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to retrieve prev private key from vault: {e}",
                    ) from e

        return response
