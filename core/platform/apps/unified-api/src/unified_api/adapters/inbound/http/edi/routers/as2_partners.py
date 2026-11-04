import structlog
from edi.application.use_cases.as2_partners import (
    CreateAS2PartnerUseCase,
    DeleteAS2PartnerUseCase,
    RotateAS2CertificatesUseCase,
    UpdateAS2PartnerUseCase,
)
from edi.application.use_cases.as2_partners.create_as2_partner_use_case import (
    CreateAS2TradingPartnerCmd,
)
from edi.application.use_cases.as2_partners.rotate_as2_certificates_use_case import (
    RotateAS2CertificateCmd,
)
from edi.application.use_cases.as2_partners.update_as2_partner_use_case import (
    UpdateAS2TradingPartnerCmd,
)
from edi.config.constants import SecretCategory
from edi.domain.exceptions import (
    IdempotencyConflictError,
    OrchestrationError,
)
from edi.ports.outbound.certificate_generator_port import CertificateGeneratorPort
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort
from fastapi import APIRouter, Depends, HTTPException, status
from identity.domain.identity_context import PLATFORM_TENANT_ID
from secret_store.ports.secret_store_port import SecretStorePort
from seedwork.domain.types import UNSET, JsonDict

from unified_api.adapters.inbound.http.dependencies.edi.auth import get_platform_user_profile
from unified_api.adapters.inbound.http.dependencies.edi.database import get_control_plane_uow
from unified_api.adapters.inbound.http.dependencies.edi.headers import get_idempotency_key
from unified_api.adapters.inbound.http.dependencies.edi.services import (
    get_certificate_generator,
    get_secret_store,
)
from unified_api.adapters.inbound.http.edi.dtos.dtos import (
    AS2TradingPartnerResponse,
    CertificateExportResponse,
    CreateAS2TradingPartnerRequest,
    GenerateCertRequest,
    GenerateCertResponse,
    RotateCertificateRequest,
    UpdateAS2TradingPartnerRequest,
)
from unified_api.adapters.inbound.http.edi.error_mapper import raise_http_for_edi_error
from unified_api.settings import get_settings

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Partners - AS2"])


@router.post(
    "/as2/certificates/generate",
    response_model=GenerateCertResponse,
    status_code=status.HTTP_200_OK,
)
async def generate_certificate(
    request: GenerateCertRequest,
    secret_store: SecretStorePort = Depends(get_secret_store),
    certificate_generator: CertificateGeneratorPort = Depends(get_certificate_generator),
) -> GenerateCertResponse:
    """
    Generates a new self-signed AS2 certificate and stores the private key in Vault.
    Returns the public cert PEM and the vault reference for the private key.
    """
    private_key_bytes, public_cert_bytes = certificate_generator.generate_self_signed_cert(
        common_name=request.as2_id
    )

    private_key_vault_ref = await secret_store.store_private_key(
        private_key_pem=private_key_bytes,
        category=SecretCategory.AS2_KEY,
    )

    return GenerateCertResponse(
        public_cert_pem=public_cert_bytes.decode("utf-8"),
        private_key_vault_ref=private_key_vault_ref,
    )


def _has_permission(profile: JsonDict, permission: str) -> bool:
    permissions = profile.get("permissions")
    return isinstance(permissions, list) and permission in permissions


async def _rotate_as2_certificates(
    partner_id: str,
    request: RotateCertificateRequest,
    tenant_id: str,
    uow: ControlPlaneUnitOfWorkPort,
    idempotency_key: str | None,
    profile: JsonDict,
    secret_store: SecretStorePort,
    certificate_generator: CertificateGeneratorPort,
) -> AS2TradingPartnerResponse:
    """Shared coroutine for certificate rotation workflow."""
    partner = await uow.as2_partners.get_as2_partner(tenant_id, partner_id)
    if not partner:
        raise HTTPException(status_code=404, detail="Partner not found")

    if not _has_permission(profile, "certificates:rotate"):
        raise HTTPException(
            status_code=403, detail="Insufficient permissions to rotate certificates."
        )

    cmd = RotateAS2CertificateCmd(
        action=request.action,
        public_cert_pem=request.public_cert_pem,
        private_key_pem=request.private_key_pem,
    )

    try:
        use_case = RotateAS2CertificatesUseCase(
            uow=uow,
            certificate_generator=certificate_generator,
        )
        rot_res = await use_case.execute(
            tenant_id=tenant_id,
            partner_id=partner_id,
            cmd=cmd,
            secret_store=secret_store,
            idempotency_key=idempotency_key,
        )
        if rot_res.is_err:
            raise_http_for_edi_error(rot_res.unwrap_err())
        updated_partner = rot_res.unwrap()
        await uow.commit()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error during certificate rotation", reason=str(e))
        raise HTTPException(status_code=500, detail="Internal server error") from e

    return AS2TradingPartnerResponse(
        id=str(updated_partner.id),
        name=updated_partner.name,
        as2_id=partner.as2_id,
        is_local=partner.is_local,
        url=partner.url,
        active=updated_partner.active,
    )


@router.put(
    "/as2/certificates/{partner_id}/rotate",
    response_model=AS2TradingPartnerResponse,
)
async def rotate_as2_certificates(
    partner_id: str,
    request: RotateCertificateRequest,
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
    idempotency_key: str | None = Depends(get_idempotency_key),
    profile: JsonDict = Depends(get_platform_user_profile),
    secret_store: SecretStorePort = Depends(get_secret_store),
    certificate_generator: CertificateGeneratorPort = Depends(get_certificate_generator),
) -> AS2TradingPartnerResponse:
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
            certificate_generator=certificate_generator,
        )


@router.get(
    "/as2/certificates/{partner_id}/export",
    response_model=CertificateExportResponse,
)
async def export_as2_certificates(
    partner_id: str,
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
    idempotency_key: str | None = Depends(get_idempotency_key),
    profile: JsonDict = Depends(get_platform_user_profile),
    secret_store: SecretStorePort = Depends(get_secret_store),
) -> CertificateExportResponse:
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
            if not _has_permission(profile, "certificates:export_private"):
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
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
) -> None:
    """Deletes an orphaned private key from Vault if the UI discards it before saving."""
    normalized_ref = vault_ref.removeprefix("vault://").strip("/")
    parts = normalized_ref.split("/")
    if (
        len(parts) < 2
        or any(not part or part in {".", ".."} for part in parts)
        or parts[-2] != SecretCategory.AS2_KEY.value
    ):
        raise HTTPException(status_code=400, detail="Invalid vault reference category.")

    async with uow:
        in_use = await uow.as2_partners.is_vault_ref_in_use(PLATFORM_TENANT_ID, vault_ref)
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
async def create_as2_partner(
    request: CreateAS2TradingPartnerRequest,
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
    idempotency_key: str | None = Depends(get_idempotency_key),
    secret_store: SecretStorePort = Depends(get_secret_store),
    _profile: JsonDict = Depends(get_platform_user_profile),
) -> AS2TradingPartnerResponse:
    """
    Creates a new Global AS2 Trading Partner (Local or Remote) in the Control Plane.
    If is_local is True, automatically generates a self-signed cert and stores private key in Vault.
    """
    logger.info(
        "create_as2_partner_request_received",
        name=request.name if request.name is not None else UNSET,
        as2_id=request.as2_id if request.as2_id is not None else UNSET,
        is_local=request.is_local if request.is_local is not None else UNSET,
        has_idempotency_key=bool(idempotency_key),
    )

    url = str(request.url) if request.url else None
    if request.is_local and not url:
        settings = get_settings()
        configured_url = settings.as2_receive_url.strip() if settings.as2_receive_url else ""
        if not configured_url:
            raise HTTPException(
                status_code=400,
                detail="AS2 receive URL must be configured (AS2_RECEIVE_URL) or explicitly provided for local stations.",
            )
        url = configured_url

    cmd = CreateAS2TradingPartnerCmd(
        name=request.name,
        as2_id=request.as2_id,
        is_local=request.is_local,
        url=url,
        public_cert_pem=request.public_cert_pem,
        private_key_pem=request.private_key_pem,
        public_cert_vault_ref=request.public_cert_vault_ref,
        private_key_vault_ref=request.private_key_vault_ref,
    )

    try:
        use_case = CreateAS2PartnerUseCase(uow=uow, secret_store=secret_store)
        create_res = await use_case.execute(
            tenant_id=PLATFORM_TENANT_ID,
            cmd=cmd,
            idempotency_key=idempotency_key,
        )
        if create_res.is_err:
            raise_http_for_edi_error(create_res.unwrap_err())
        entity = create_res.unwrap()
        await uow.commit()

        p = await uow.as2_partners.get_as2_partner(
            tenant_id=PLATFORM_TENANT_ID, partner_id=entity.id
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
    except HTTPException:
        raise
    except IdempotencyConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except OrchestrationError as e:
        raise HTTPException(
            status_code=500, detail="Failed to orchestrate AS2 partner creation"
        ) from e


@router.get("/as2/trading-partners", response_model=list[AS2TradingPartnerResponse])
async def list_as2_partners(
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
) -> list[AS2TradingPartnerResponse]:
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
async def update_as2_partner(
    partner_id: str,
    request: UpdateAS2TradingPartnerRequest,
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
    idempotency_key: str | None = Depends(get_idempotency_key),
) -> AS2TradingPartnerResponse:
    """Updates a global AS2 partner."""
    logger.info(
        "api_update_as2_partner_request_received",
        partner_id=partner_id,
        fields_set=list(request.model_fields_set),
    )
    async with uow:
        use_case = UpdateAS2PartnerUseCase(uow=uow)
        cmd = UpdateAS2TradingPartnerCmd(**request.model_dump(mode="json", exclude_unset=True))
        try:
            upd_res = await use_case.execute(
                tenant_id=PLATFORM_TENANT_ID,
                partner_id=partner_id,
                cmd=cmd,
                idempotency_key=idempotency_key,
            )
            if upd_res.is_err:
                raise_http_for_edi_error(upd_res.unwrap_err())

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
async def delete_as2_partner(
    partner_id: str,
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
    idempotency_key: str | None = Depends(get_idempotency_key),
) -> None:
    """Deletes an AS2 partner."""
    async with uow:
        use_case = DeleteAS2PartnerUseCase(uow=uow)
        try:
            del_res = await use_case.execute(
                tenant_id=PLATFORM_TENANT_ID,
                partner_id=partner_id,
                idempotency_key=idempotency_key,
            )
            if del_res.is_err:
                raise_http_for_edi_error(del_res.unwrap_err())
            await uow.commit()
        except HTTPException:
            raise
        except OrchestrationError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
