from typing import Any

from config.settings import get_settings
from edi.adapters.outbound.database.uow_adapter import (
    SqlAlchemyControlPlaneUnitOfWork as ControlPlaneUnitOfWork,
)
from edi.application.use_cases.as2_partners import (
    CreateAS2PartnerUseCase,
    DeleteAS2PartnerUseCase,
    RotateAS2CertificatesUseCase,
    UpdateAS2PartnerUseCase,
)
from edi.domain.certificate import generate_self_signed_cert
from edi.domain.exceptions import (
    IdempotencyConflictError,
    OrchestrationError,
    PartnerAlreadyExistsError,
    PartnerInUseError,
)
from edi.domain.models import (
    CreateAS2TradingPartnerCmd,
    RotateAS2CertificateCmd,
    UpdateAS2TradingPartnerCmd,
)
from edi.ports.outbound.secret_store import SecretStorePort
from fastapi import APIRouter, Depends, HTTPException, status
from identity.domain.identity_context import PLATFORM_TENANT_ID

from unified_api.adapters.inbound.http.dependencies.edi.auth import get_platform_user_profile
from unified_api.adapters.inbound.http.dependencies.edi.database import get_control_plane_uow
from unified_api.adapters.inbound.http.dependencies.edi.headers import get_idempotency_key
from unified_api.adapters.inbound.http.dependencies.edi.services import get_secret_store
from unified_api.adapters.inbound.http.dtos.edi.dtos import (
    AS2TradingPartnerResponse,
    CreateAS2TradingPartnerRequest,
    GenerateCertRequest,
    GenerateCertResponse,
    RotateCertificateRequest,
    UpdateAS2TradingPartnerRequest,
)

router = APIRouter(tags=["Platform Partners - AS2"])


@router.post(
    "/as2/certificates/generate",
    response_model=GenerateCertResponse,
    status_code=status.HTTP_200_OK,
)
async def generate_certificate(
    request: GenerateCertRequest,
    secret_store: SecretStorePort = Depends(get_secret_store),
) -> Any:
    """
    Generates a new self-signed AS2 certificate and stores the private key in Vault.
    Returns the public cert PEM and the vault reference for the private key.
    """
    private_key_bytes, public_cert_bytes = generate_self_signed_cert(common_name=request.as2_id)

    from config.constants import SecretCategory

    private_key_vault_ref = await secret_store.store_private_key(
        private_key_pem=private_key_bytes,
        category=SecretCategory.AS2_KEY,
    )

    return GenerateCertResponse(
        public_cert_pem=public_cert_bytes.decode("utf-8"),
        private_key_vault_ref=private_key_vault_ref,
    )


import structlog

from unified_api.adapters.inbound.http.dtos.edi.dtos import CertificateExportResponse

logger = structlog.get_logger(__name__)


async def _rotate_as2_certificates(
    partner_id: str,
    request: RotateCertificateRequest,
    tenant_id: str,
    uow: ControlPlaneUnitOfWork,
    idempotency_key: str | None,
    profile: dict[str, Any],
    secret_store: SecretStorePort,
) -> AS2TradingPartnerResponse:
    """Shared coroutine for certificate rotation workflow."""
    partner = await uow.as2_partners.get_as2_partner(tenant_id, partner_id)
    if not partner:
        raise HTTPException(status_code=404, detail="Partner not found")

    # Require certificates:rotate for all partners
    if "certificates:rotate" not in profile["permissions"]:
        raise HTTPException(
            status_code=403, detail="Insufficient permissions to rotate certificates."
        )

    cmd = RotateAS2CertificateCmd(
        action=request.action,
        public_cert_pem=request.public_cert_pem,
        private_key_pem=request.private_key_pem,
    )

    try:
        use_case = RotateAS2CertificatesUseCase(uow=uow)
        updated_partner = await use_case.execute(
            tenant_id=tenant_id,
            partner_id=partner_id,
            cmd=cmd,
            secret_store=secret_store,
            idempotency_key=idempotency_key,
        )
        await uow.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Unexpected error during certificate rotation")
        raise HTTPException(status_code=500, detail="Internal server error") from e

    return AS2TradingPartnerResponse(
        id=str(updated_partner.partner_id),
        name=updated_partner.name,
        as2_id=partner.as2_id,
        is_local=partner.is_local,
        url=partner.url,
        active=updated_partner.status == "ACTIVE",
    )


@router.put(
    "/as2/certificates/{partner_id}/rotate",
    response_model=AS2TradingPartnerResponse,
)
async def rotate_platform_as2_certificates(
    partner_id: str,
    request: RotateCertificateRequest,
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
    idempotency_key: str | None = Depends(get_idempotency_key),
    profile: dict[str, Any] = Depends(get_platform_user_profile),
    secret_store: SecretStorePort = Depends(get_secret_store),
) -> Any:
    """Rotates certificates for a Platform AS2 partner."""
    async with uow:
        return await _rotate_as2_certificates(
            partner_id=partner_id,
            request=request,
            tenant_id=PLATFORM_TENANT_ID,
            uow=uow,
            idempotency_key=idempotency_key,
            profile=profile,
            secret_store=secret_store,
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
    secret_store: SecretStorePort = Depends(get_secret_store),
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


@router.delete(
    "/as2/certificates/secret",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_certificate_secret(
    vault_ref: str,
    secret_store: SecretStorePort = Depends(get_secret_store),
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> None:
    """Deletes an orphaned private key from Vault if the UI discards it before saving."""
    async with uow:
        in_use = await uow.as2_partners.is_vault_ref_in_use(vault_ref)
        if in_use:
            raise HTTPException(
                status_code=400, detail="Cannot delete a private key that is currently in use."
            )

        await secret_store.delete_secret(vault_ref)


@router.post(
    "/as2/trading-partners",
    response_model=AS2TradingPartnerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_platform_as2_partner(
    request: CreateAS2TradingPartnerRequest,
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
    idempotency_key: str | None = Depends(get_idempotency_key),
    secret_store: SecretStorePort = Depends(get_secret_store),
    _: Any = Depends(get_platform_user_profile),
) -> Any:
    """
    Creates a new Global AS2 Trading Partner (Local or Remote) in the Control Plane.
    If is_local is True, automatically generates a self-signed cert and stores private key in Vault.
    """
    logger.info(
        "create_platform_as2_partner_request_received",
        name=request.name,
        as2_id=request.as2_id,
        is_local=request.is_local,
        has_idempotency_key=bool(idempotency_key),
    )

    url = str(request.url) if request.url else None
    if request.is_local and not url:
        settings = get_settings()
        url = f"{settings.public.base_url}/api/v1/as2/receive"

    cmd = CreateAS2TradingPartnerCmd(
        name=request.name,
        as2_id=request.as2_id,
        is_local=request.is_local,
        url=url,
        public_cert_pem=request.public_cert_pem,
        public_cert_vault_ref=request.public_cert_vault_ref,
        private_key_vault_ref=request.private_key_vault_ref,
    )

    try:
        use_case = CreateAS2PartnerUseCase(uow=uow, secret_store=secret_store)
        entity = await use_case.execute(
            tenant_id=PLATFORM_TENANT_ID,
            cmd=cmd,
            idempotency_key=idempotency_key,
        )
        await uow.commit()

        # Re-fetch from DB to get the actual ID (or we can just return entity if it has the ID)
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
        raise HTTPException(status_code=409, detail=str(e)) from e
    except PartnerAlreadyExistsError as e:
        raise HTTPException(status_code=400, detail="AS2 ID already exists for this tenant.") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OrchestrationError as e:
        raise HTTPException(
            status_code=500, detail="Failed to orchestrate AS2 partner creation"
        ) from e


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
        use_case = UpdateAS2PartnerUseCase(uow=uow)
        cmd = UpdateAS2TradingPartnerCmd(
            name=request.name,
            as2_id=request.as2_id,
            is_local=request.is_local,
            url=str(request.url) if request.url else None,
            active=request.active,
        )
        try:
            await use_case.execute(
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
        except PartnerAlreadyExistsError as e:
            raise HTTPException(
                status_code=400, detail="AS2 ID already exists for this tenant."
            ) from e
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
        use_case = DeleteAS2PartnerUseCase(uow=uow)
        try:
            await use_case.execute(
                tenant_id=PLATFORM_TENANT_ID,
                partner_id=partner_id,
                idempotency_key=idempotency_key,
            )
            await uow.commit()
        except PartnerInUseError as e:
            raise HTTPException(
                status_code=400, detail="Partner is in use and cannot be deleted."
            ) from e
        except OrchestrationError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
