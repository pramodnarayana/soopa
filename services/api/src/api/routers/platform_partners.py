from typing import Any
from uuid import UUID

from database.models.control_plane import AS2Partner, AS2Partnership
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api.adapters.http.dtos import (
    AS2PartnershipResponse,
    AS2TradingPartnerResponse,
    CreateAS2PartnershipRequest,
    CreateAS2TradingPartnerRequest,
    UpdateAS2PartnershipRequest,
    UpdateAS2TradingPartnerRequest,
)
from api.adapters.vault import vault
from api.core.provisioning import ProvisioningService
from api.core.uow import UnitOfWork
from api.dependencies import (
    get_uow,
    require_platform_admin,
)
from api.domain.certificate import generate_self_signed_cert
from api.domain.models import (
    CreateAS2PartnershipCmd,
    CreateAS2TradingPartnerCmd,
    UpdateAS2PartnershipCmd,
    UpdateAS2TradingPartnerCmd,
)

# Enforce require_platform_admin on all routes in this router
router = APIRouter(
    prefix="/api/v1/platform/partners",
    tags=["Platform Partners"],
    dependencies=[Depends(require_platform_admin)],
)


@router.post(
    "/as2/trading-partners",
    response_model=AS2TradingPartnerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_platform_as2_partner(
    request: CreateAS2TradingPartnerRequest,
    uow: UnitOfWork = Depends(get_uow),
) -> Any:
    """
    Creates a new Global AS2 Trading Partner (Local or Remote) in the Control Plane.
    If is_local is True, automatically generates a self-signed cert and stores private key in Vault.
    """
    try:
        async with uow:
            public_cert_pem = request.public_cert_pem
            private_key_vault_ref = request.private_key_vault_ref

            if request.is_local:
                # Auto-generate self-signed cert
                private_key_bytes, public_cert_bytes = generate_self_signed_cert(
                    common_name=request.as2_id
                )

                # Store in Vault
                private_key_vault_ref = vault.store_private_key(
                    private_key_pem=private_key_bytes,
                    alias_prefix=request.name.replace(" ", "_").lower(),
                )

                public_cert_pem = public_cert_bytes.decode("utf-8")

            cmd = CreateAS2TradingPartnerCmd(
                name=request.name,
                as2_id=request.as2_id,
                is_local=request.is_local,
                url=str(request.url) if request.url else None,
                public_cert_pem=public_cert_pem,
                public_cert_vault_ref=request.public_cert_vault_ref,
                private_key_vault_ref=private_key_vault_ref,
            )

            # Use tenant_id=0 for global platform partners
            partner_id = await uow.control_plane.create_as2_identity(tenant_id=0, cmd=cmd)

            await uow.commit()

            return AS2TradingPartnerResponse(
                id=str(partner_id),
                name=request.name,
                as2_id=request.as2_id,
                is_local=request.is_local,
                url=str(request.url) if request.url else None,
            )
    except IntegrityError as e:
        raise HTTPException(status_code=400, detail="AS2 ID already exists for this tenant.") from e
    except Exception:
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Internal error creating platform AS2 partner")

        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=500, content={"detail": "An internal server error occurred."}
        )


@router.get("/as2/trading-partners", response_model=list[AS2TradingPartnerResponse])
async def list_platform_as2_partners(
    uow: UnitOfWork = Depends(get_uow),
) -> Any:
    """
    Returns all global AS2 partners (tenant_id = 0).
    """
    async with uow:
        result = await uow.global_session.execute(
            select(AS2Partner).where(AS2Partner.tenant_id == 0)
        )
        partners = result.scalars().all()

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
    partner_id: UUID,
    request: UpdateAS2TradingPartnerRequest,
    uow: UnitOfWork = Depends(get_uow),
) -> Any:
    """Updates a global AS2 partner."""
    async with uow:
        cmd = UpdateAS2TradingPartnerCmd(
            name=request.name,
            as2_id=request.as2_id,
            is_local=request.is_local,
            url=str(request.url) if request.url else None,
            active=request.active,
        )
        try:
            await uow.control_plane.update_as2_identity(tenant_id=0, partner_id=partner_id, cmd=cmd)
            updated_partner = await uow.control_plane.get_as2_partner(
                tenant_id=0, partner_id=partner_id
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
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/as2/trading-partners/{partner_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_platform_as2_partner(
    partner_id: UUID,
    uow: UnitOfWork = Depends(get_uow),
) -> None:
    """Deletes an AS2 partner."""
    async with uow:
        svc = ProvisioningService(tenant_repo=None, global_repo=uow.control_plane)  # type: ignore[arg-type]
        try:
            await svc.delete_as2_partner(tenant_id=0, partner_id=partner_id)
            await uow.commit()
        except Exception as e:
            if "IntegrityError" in str(type(e)):
                raise HTTPException(
                    status_code=400, detail="Partner is in use and cannot be deleted."
                ) from e
            raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/as2/partnerships", response_model=Any, status_code=status.HTTP_201_CREATED)
async def create_platform_as2_partnership(
    request: CreateAS2PartnershipRequest,
    uow: UnitOfWork = Depends(get_uow),
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
                mdn_type=request.mdn_type,
                mdn_url=str(request.mdn_url) if request.mdn_url else None,
                encryption_algorithm=request.encryption_algorithm,
                signature_algorithm=request.signature_algorithm,
                edi_version=request.edi_version,
                advanced_flags=request.advanced_flags,
            )

            partnership_id = await uow.control_plane.create_as2_partnership(tenant_id=0, cmd=cmd)
            await uow.commit()

            return AS2PartnershipResponse(
                id=str(partnership_id),
                tenant_id=0,
                name=request.name,
                local_partner_id=str(request.local_partner_id),
                remote_partner_id=str(request.remote_partner_id),
                mdn_type=request.mdn_type,
                mdn_url=str(request.mdn_url) if request.mdn_url else None,
                encryption_algorithm=request.encryption_algorithm,
                signature_algorithm=request.signature_algorithm,
                edi_version=request.edi_version,
                status="active",
            )
    except Exception:
        import logging

        from fastapi.responses import JSONResponse

        logger = logging.getLogger(__name__)
        logger.exception("Internal error creating platform AS2 partner")

        return JSONResponse(
            status_code=500, content={"detail": "An internal server error occurred."}
        )


@router.put("/as2/partnerships/{partnership_id}", response_model=AS2PartnershipResponse)
async def update_platform_as2_partnership(
    partnership_id: UUID,
    request: UpdateAS2PartnershipRequest,
    uow: UnitOfWork = Depends(get_uow),
) -> Any:
    try:
        async with uow:
            cmd = UpdateAS2PartnershipCmd(
                name=request.name,
                local_partner_id=request.local_partner_id,
                remote_partner_id=request.remote_partner_id,
                credentials_vault_ref=request.credentials_vault_ref,
                mdn_type=request.mdn_type,
                mdn_url=str(request.mdn_url) if request.mdn_url else None,
                encryption_algorithm=request.encryption_algorithm,
                signature_algorithm=request.signature_algorithm,
                edi_version=request.edi_version,
                advanced_flags=request.advanced_flags,
                active=request.active,
            )
            await uow.control_plane.update_as2_partnership(
                tenant_id=0, partnership_id=partnership_id, cmd=cmd
            )
            await uow.commit()

            p = await uow.control_plane.get_as2_partnership(
                tenant_id=0, partnership_id=partnership_id
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
                edi_version=p.edi_version,
                status="active" if p.active else "inactive",
                active=p.active,
            )
    except Exception:
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Internal error updating platform AS2 partnership")
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=500, content={"detail": "An internal server error occurred."}
        )


@router.delete(
    "/as2/partnerships/{partnership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_platform_as2_partnership(
    partnership_id: UUID,
    uow: UnitOfWork = Depends(get_uow),
) -> None:
    try:
        async with uow:
            await uow.control_plane.delete_as2_partnership(
                tenant_id=0, partnership_id=partnership_id
            )
            await uow.commit()
    except Exception as err:
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Internal error deleting platform AS2 partnership")
        raise HTTPException(status_code=500, detail="An internal server error occurred.") from err


@router.get("/as2/partnerships", response_model=list[AS2PartnershipResponse])
async def list_platform_as2_partnerships(
    uow: UnitOfWork = Depends(get_uow),
) -> Any:
    """
    Returns all global AS2 partnerships (tenant_id = 0).
    """
    async with uow:
        result = await uow.global_session.execute(
            select(AS2Partnership).where(AS2Partnership.tenant_id == 0)
        )
        partnerships = result.scalars().all()

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
                edi_version=p.edi_version,
                status="active" if p.active else "inactive",
                active=p.active,
            )
            for p in partnerships
        ]
