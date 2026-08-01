import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError

from api.adapters.http.dtos import (
    AS2PartnershipResponse,
    CreateAS2PartnershipRequest,
    TestAS2ConnectionRequest,
    TestAS2ConnectionResponse,
    UpdateAS2PartnershipRequest,
)
from api.core.services import AS2PartnershipService
from api.core.uow import ControlPlaneUnitOfWork
from api.dependencies.database import get_control_plane_uow
from api.dependencies.services import get_as2_tester, get_vault
from api.domain.models import (
    CreateAS2PartnershipCmd,
    EncryptionAlgorithm,
    MDNType,
    SignatureAlgorithm,
    UpdateAS2PartnershipCmd,
)
from api.ports.as2_tester import AS2TesterPort
from api.ports.vault import VaultPort

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Platform Partners - AS2 Partnerships"])


@router.post(
    "/as2/partnerships/{partnership_id}/test",
    response_model=TestAS2ConnectionResponse,
    status_code=status.HTTP_200_OK,
)
async def test_as2_partnership_connection(
    partnership_id: str,
    request: TestAS2ConnectionRequest | None = None,
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
    as2_tester: AS2TesterPort = Depends(get_as2_tester),
    vault_port: VaultPort = Depends(get_vault),
) -> Any:
    """
    Tests an AS2 connection for a configured partnership.

    Sends a synthetic AS2 ping (or custom payload) to the remote partner's URL
    using the partnership's configured cryptographic material.
    """
    async with uow:
        partnership = await uow.as2_partnerships.get_as2_partnership(
            tenant_id="0", partnership_id=partnership_id
        )
        if not partnership:
            raise HTTPException(status_code=404, detail="Partnership not found")

        local_partner = await uow.as2_partners.get_as2_partner(
            tenant_id="0", partner_id=partnership.local_partner_id
        )
        remote_partner = await uow.as2_partners.get_as2_partner(
            tenant_id="0", partner_id=partnership.remote_partner_id
        )

    if not local_partner:
        return TestAS2ConnectionResponse(
            success=False, reason="Local AS2 partner not found for this partnership."
        )
    if not remote_partner:
        return TestAS2ConnectionResponse(
            success=False, reason="Remote AS2 partner not found for this partnership."
        )
    if not remote_partner.url:
        return TestAS2ConnectionResponse(
            success=False, reason="Remote partner has no URL configured."
        )

    # Resolve cryptographic material from Vault or inline PEM
    local_private_key_pem: bytes | None = None
    local_cert_pem: bytes | None = None
    remote_cert_pem: bytes | None = None

    try:
        if local_partner.private_key_vault_ref:
            local_private_key_pem = vault_port.retrieve_secret(local_partner.private_key_vault_ref)
        if local_partner.public_cert_vault_ref:
            local_cert_pem = vault_port.retrieve_secret(local_partner.public_cert_vault_ref)
        elif local_partner.public_cert_pem:
            local_cert_pem = local_partner.public_cert_pem.encode()
        if remote_partner.public_cert_vault_ref:
            remote_cert_pem = vault_port.retrieve_secret(remote_partner.public_cert_vault_ref)
        elif remote_partner.public_cert_pem:
            remote_cert_pem = remote_partner.public_cert_pem.encode()
    except Exception as e:
        return TestAS2ConnectionResponse(
            success=False, reason=f"Failed to retrieve cryptographic material: {e}"
        )

    transport_ok, raw_disposition, sent_payload, raw_mdn = await as2_tester.test_connection(
        remote_url=str(remote_partner.url),
        as2_from=local_partner.as2_id,
        as2_to=remote_partner.as2_id,
        local_private_key_pem=local_private_key_pem,
        local_cert_pem=local_cert_pem,
        remote_cert_pem=remote_cert_pem,
        encryption_algorithm=partnership.encryption_algorithm or "AES256",
        signature_algorithm=partnership.signature_algorithm or "SHA256",
        custom_payload=request.custom_payload if request else None,
    )

    if not transport_ok:
        return TestAS2ConnectionResponse(
            success=False, reason=raw_disposition, sent_payload=sent_payload, raw_mdn=raw_mdn
        )

    # Business rule (RFC 4130): MDN disposition must start with "processed"
    disposition = raw_disposition or ""
    parts = disposition.split(";", 1)
    status_part = parts[1].strip().lower() if len(parts) == 2 else disposition.strip().lower()
    is_success = (
        status_part.startswith("processed")
        and "error" not in status_part
        and "failed" not in status_part
    )

    return TestAS2ConnectionResponse(
        success=is_success,
        mdn_disposition=status_part,
        reason=None if is_success else status_part or disposition,
        sent_payload=sent_payload,
        raw_mdn=raw_mdn,
    )


@router.post("/as2/partnerships", response_model=Any, status_code=status.HTTP_201_CREATED)
async def create_platform_as2_partnership(
    request: CreateAS2PartnershipRequest,
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> Any:
    """
    Creates a new AS2 Partnership directly in the Control Plane (used by Platform Admins).
    """
    try:
        async with uow:
            cmd = CreateAS2PartnershipCmd(
                name=request.name,
                local_partner_id=request.local_partner_id,
                remote_partner_id=request.remote_partner_id,
                credentials_vault_ref=request.credentials_vault_ref,
                mdn_type=MDNType(request.mdn_type),
                mdn_url=str(request.mdn_url) if request.mdn_url else None,
                encryption_algorithm=EncryptionAlgorithm(request.encryption_algorithm),
                signature_algorithm=SignatureAlgorithm(request.signature_algorithm),
                advanced_flags=request.advanced_flags,
            )

            svc = AS2PartnershipService(uow=uow)
            entity = await svc.create_as2_partnership(tenant_id="0", cmd=cmd)
            await uow.commit()
            p = await uow.as2_partnerships.get_as2_partnership(
                tenant_id="0", partnership_id=entity.partner_id
            )
            if not p:
                raise HTTPException(status_code=404, detail="Partnership not found")

            return AS2PartnershipResponse(
                id=str(entity.partner_id),
                tenant_id="0",
                name=p.name,
                local_partner_id=str(p.local_partner_id),
                remote_partner_id=str(p.remote_partner_id),
                mdn_type=p.mdn_type,
                mdn_url=p.mdn_url,
                encryption_algorithm=p.encryption_algorithm,
                signature_algorithm=p.signature_algorithm,
                status="active" if p.active else "inactive",
                active=p.active,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except IntegrityError as e:
        raise HTTPException(
            status_code=400, detail="AS2 Partnership already exists for these partners."
        ) from e
    except HTTPException:
        raise


@router.put("/as2/partnerships/{partnership_id}", response_model=AS2PartnershipResponse)
async def update_platform_as2_partnership(
    partnership_id: str,
    request: UpdateAS2PartnershipRequest,
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> Any:
    try:
        async with uow:
            from api.domain.models import UNSET

            def get_val(field: str) -> Any:
                return getattr(request, field) if field in request.model_fields_set else UNSET

            mdn_url_val = get_val("mdn_url")
            if mdn_url_val not in (UNSET, None):
                mdn_url_val = str(mdn_url_val)

            cmd = UpdateAS2PartnershipCmd(
                name=get_val("name"),
                local_partner_id=get_val("local_partner_id"),
                remote_partner_id=get_val("remote_partner_id"),
                credentials_vault_ref=get_val("credentials_vault_ref"),
                mdn_type=get_val("mdn_type"),
                mdn_url=mdn_url_val,
                encryption_algorithm=get_val("encryption_algorithm"),
                signature_algorithm=get_val("signature_algorithm"),
                advanced_flags=get_val("advanced_flags"),
                active=get_val("active"),
            )
            svc = AS2PartnershipService(uow=uow)
            await svc.update_as2_partnership(tenant_id="0", partnership_id=partnership_id, cmd=cmd)
            await uow.commit()

            p = await uow.as2_partnerships.get_as2_partnership(
                tenant_id="0", partnership_id=partnership_id
            )
            if not p:
                raise HTTPException(status_code=404, detail="Partnership not found")

            return AS2PartnershipResponse(
                id=str(p.id),
                tenant_id=p.tenant_id,
                name=p.name,
                local_partner_id=str(p.local_partner_id),
                remote_partner_id=str(p.remote_partner_id),
                mdn_type=p.mdn_type,
                mdn_url=p.mdn_url,
                encryption_algorithm=p.encryption_algorithm,
                signature_algorithm=p.signature_algorithm,
                status="active" if p.active else "inactive",
                active=p.active,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except IntegrityError as e:
        raise HTTPException(
            status_code=400, detail="AS2 Partnership already exists for these partners."
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete(
    "/as2/partnerships/{partnership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_platform_as2_partnership(
    partnership_id: str,
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> None:
    try:
        async with uow:
            svc = AS2PartnershipService(uow=uow)
            await svc.delete_as2_partnership(tenant_id="0", partnership_id=partnership_id)
            await uow.commit()
    except Exception as err:
        logger.exception("Internal error deleting platform AS2 partnership")
        raise HTTPException(status_code=500, detail="An internal server error occurred.") from err


@router.get("/as2/partnerships", response_model=list[AS2PartnershipResponse])
async def list_platform_as2_partnerships(
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> Any:
    """
    Returns all global AS2 partnerships (tenant_id = 0).
    """
    async with uow:
        partnerships = await uow.as2_partnerships.list_as2_partnerships(tenant_id="0")

        return [
            AS2PartnershipResponse(
                id=str(p.id),
                tenant_id=p.tenant_id,
                name=p.name,
                local_partner_id=str(p.local_partner_id),
                remote_partner_id=str(p.remote_partner_id),
                mdn_type=p.mdn_type,
                mdn_url=p.mdn_url,
                encryption_algorithm=p.encryption_algorithm,
                signature_algorithm=p.signature_algorithm,
                status="active" if p.active else "inactive",
                active=p.active,
            )
            for p in partnerships
        ]
