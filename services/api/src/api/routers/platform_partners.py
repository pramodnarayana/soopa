from typing import Any

from database.models.control_plane import AS2Partner, AS2Partnership
from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from api.adapters.http.dtos import (
    AS2PartnershipResponse,
    AS2TradingPartnerResponse,
    CreateAS2PartnershipRequest,
    CreateAS2TradingPartnerRequest,
)
from api.adapters.vault import vault
from api.core.uow import UnitOfWork
from api.dependencies import (
    get_uow,
    require_platform_admin,
)
from api.domain.certificate import generate_self_signed_cert
from api.domain.models import CreateAS2PartnershipCmd, CreateAS2TradingPartnerCmd

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
            )
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
            )
            for p in partners
        ]


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
            allow_insecure = (
                request.advanced_flags.get("allow_insecure", False)
                if request.advanced_flags
                else False
            )
            scheme = "http" if allow_insecure else "https"

            cmd = CreateAS2PartnershipCmd(
                local_partner_id=request.local_partner_id,
                remote_partner_id=request.remote_partner_id,
                local_url=None,
                remote_url=f"{scheme}://{request.host}:{request.port}" if request.host else None,
                credentials_vault_ref=request.credentials_vault_ref,
                mdn_type=request.mdn_type,
                mdn_url=request.mdn_url,
                encryption_algorithm=request.encryption_algorithm,
                signature_algorithm=request.signature_algorithm,
                advanced_flags=request.advanced_flags,
            )

            partnership_id = await uow.control_plane.create_as2_partnership(tenant_id=0, cmd=cmd)
            await uow.commit()

            return AS2PartnershipResponse(
                id=str(partnership_id),
                local_partner_id=str(request.local_partner_id),
                remote_partner_id=str(request.remote_partner_id),
                local_url=None,
                remote_url=f"http://{request.host}:{request.port}" if request.host else None,
                mdn_type=request.mdn_type,
                mdn_url=request.mdn_url,
                encryption_algorithm=request.encryption_algorithm,
                signature_algorithm=request.signature_algorithm,
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
                local_partner_id=str(p.local_partner_id),
                remote_partner_id=str(p.remote_partner_id),
                local_url=p.local_url,
                remote_url=p.remote_url,
                mdn_type=p.mdn_type,
                mdn_url=p.mdn_url,
                encryption_algorithm=p.encryption_algorithm,
                signature_algorithm=p.signature_algorithm,
                status="active" if p.active else "inactive",
            )
            for p in partnerships
        ]
