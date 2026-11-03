import structlog
from edi.domain.exceptions import OrchestrationError
from edi.ports.outbound.certificate_generator_port import CertificateGeneratorPort
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort
from fastapi import APIRouter, Depends, HTTPException
from identity.domain.identity_context import PLATFORM_TENANT_ID
from secret_store.ports.secret_store_port import SecretStorePort
from seedwork.domain.types import JsonDict

from unified_api.adapters.inbound.http.dependencies.edi.auth import (
    get_current_tenant_id,
    get_current_user_profile,
    get_raw_jwt,
)
from unified_api.adapters.inbound.http.dependencies.edi.database import get_control_plane_uow
from unified_api.adapters.inbound.http.dependencies.edi.headers import get_idempotency_key
from unified_api.adapters.inbound.http.dependencies.edi.services import (
    get_certificate_generator,
    get_secret_store,
)
from unified_api.adapters.inbound.http.edi.dtos.dtos import (
    AS2TradingPartnerResponse,
    CertificateExportResponse,
    RotateCertificateRequest,
)
from unified_api.adapters.inbound.http.edi.routers.as2_partners import (
    _rotate_as2_certificates,
)

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Partners — AS2"])


@router.get(
    "/as2/{partner_id}/certificates/export",
    response_model=CertificateExportResponse,
)
async def export_as2_certificates(
    partner_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
    token_payload: JsonDict = Depends(get_raw_jwt),
    profile: JsonDict = Depends(get_current_user_profile),
    secret_store: SecretStorePort = Depends(get_secret_store),
) -> CertificateExportResponse:
    """Exports current and previous certificates for an AS2 partner."""
    async with uow:
        partner = await uow.as2_partners.get_as2_partner(tenant_id, partner_id)
        if not partner:
            raise HTTPException(status_code=404, detail="Partner not found")

        response = CertificateExportResponse(
            public_cert_pem=partner.public_cert_pem,
            prev_public_cert_pem=partner.prev_public_cert_pem,
        )

        if partner.is_local:
            permissions = profile.get("permissions")
            if not isinstance(permissions, (list, tuple, set)) or (
                "certificates:export_private" not in permissions
            ):
                raise HTTPException(
                    status_code=403, detail="Insufficient permissions to export private keys."
                )

            if partner.private_key_vault_ref:
                try:
                    response.private_key_pem = (
                        await secret_store.retrieve_private_key(partner.private_key_vault_ref)
                    ).decode("utf-8")
                except OrchestrationError as e:
                    logger.exception("Failed to retrieve private key from vault")
                    raise HTTPException(
                        status_code=500, detail="Failed to retrieve private key from vault"
                    ) from e

            if partner.prev_private_key_vault_ref:
                try:
                    response.prev_private_key_pem = (
                        await secret_store.retrieve_private_key(partner.prev_private_key_vault_ref)
                    ).decode("utf-8")
                except OrchestrationError as e:
                    logger.exception("Failed to retrieve prev private key from vault")
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to retrieve prev private key from vault",
                    ) from e

        return response


@router.put(
    "/as2/certificates/{partner_id}/rotate",
    response_model=AS2TradingPartnerResponse,
)
async def rotate_as2_certificates(
    partner_id: str,
    request: RotateCertificateRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
    idempotency_key: str | None = Depends(get_idempotency_key),
    profile: JsonDict = Depends(get_current_user_profile),
    secret_store: SecretStorePort = Depends(get_secret_store),
    certificate_generator: CertificateGeneratorPort = Depends(get_certificate_generator),
) -> AS2TradingPartnerResponse:
    """Rotates certificates for an AS2 partner."""
    async with uow:
        # Resolve actual tenant ID from partner
        partner = await uow.as2_partners.get_as2_partner(tenant_id, partner_id)
        if not partner:
            raise HTTPException(status_code=404, detail="Partner not found")

        actual_tenant_id = (
            str(partner.tenant_id) if partner.tenant_id is not None else PLATFORM_TENANT_ID
        )

        return await _rotate_as2_certificates(
            partner_id=partner_id,
            request=request,
            tenant_id=actual_tenant_id,
            uow=uow,
            idempotency_key=idempotency_key,
            profile=profile,
            secret_store=secret_store,
            certificate_generator=certificate_generator,
        )
