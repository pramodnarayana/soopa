from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError

from api.adapters.http.dtos import (
    AS2TradingPartnerResponse,
    CreateAS2TradingPartnerRequest,
    GenerateCertRequest,
    GenerateCertResponse,
    UpdateAS2TradingPartnerRequest,
)
from api.core.services import AS2PartnerService
from api.core.uow import UnitOfWork
from api.dependencies import (
    get_uow,
    get_vault,
)
from api.domain.certificate import generate_self_signed_cert
from api.domain.models import (
    CreateAS2TradingPartnerCmd,
    UpdateAS2TradingPartnerCmd,
)
from api.ports.vault import VaultPort

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


@router.delete(
    "/as2/certificates/secret",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_certificate_secret(
    vault_ref: str,
    vault: VaultPort = Depends(get_vault),
    uow: UnitOfWork = Depends(get_uow),
) -> None:
    """Deletes an orphaned private key from Vault if the UI discards it before saving."""
    async with uow:
        from database.models.control_plane import AS2Partner
        from sqlalchemy import or_, select

        stmt = select(AS2Partner).where(
            or_(
                AS2Partner.private_key_vault_ref == vault_ref,
                AS2Partner.prev_private_key_vault_ref == vault_ref,
            )
        )
        res = await uow.global_session.execute(stmt)
        if res.scalars().first() is not None:
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
    uow: UnitOfWork = Depends(get_uow),
    vault: VaultPort = Depends(get_vault),
) -> Any:
    """
    Creates a new Global AS2 Trading Partner (Local or Remote) in the Control Plane.
    If is_local is True, automatically generates a self-signed cert and stores private key in Vault.
    """
    try:
        async with uow:
            public_cert_pem = request.public_cert_pem
            private_key_vault_ref = request.private_key_vault_ref

            auto_generated = False

            if request.is_local:
                if private_key_vault_ref:
                    # Pre-stored vault ref (from generate cert flow) — use as-is
                    pass
                elif request.private_key_pem:
                    # User uploaded their own cert+key — store the private key in Vault
                    auto_generated = True
                    private_key_vault_ref = vault.store_private_key(
                        private_key_pem=request.private_key_pem.encode(),
                        alias_prefix=request.name.replace(" ", "_").lower(),
                    )
                else:
                    # No cert material provided at all — auto-generate a self-signed cert
                    auto_generated = True
                    private_key_bytes, public_cert_bytes = generate_self_signed_cert(
                        common_name=request.as2_id
                    )
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
            svc = AS2PartnerService(uow=uow)
            entity = await svc.create_as2_partner(tenant_id=0, cmd=cmd)

            await uow.commit()
            p = await uow.as2_partners.get_as2_partner(tenant_id=0, partner_id=entity.partner_id)
            if not p:
                raise HTTPException(status_code=500, detail="Partner creation failed")

            return AS2TradingPartnerResponse(
                id=str(entity.partner_id),
                name=p.name,
                as2_id=p.as2_id,
                is_local=p.is_local,
                url=p.url,
                active=p.active,
            )
    except Exception as e:
        if auto_generated and private_key_vault_ref:
            vault.delete_secret(private_key_vault_ref)
        if isinstance(e, IntegrityError):
            raise HTTPException(
                status_code=400, detail="AS2 ID already exists for this tenant."
            ) from e
        raise


@router.get("/as2/trading-partners", response_model=list[AS2TradingPartnerResponse])
async def list_platform_as2_partners(
    uow: UnitOfWork = Depends(get_uow),
) -> Any:
    """
    Returns all global AS2 partners (tenant_id = 0).
    """
    async with uow:
        partners = await uow.as2_partners.list_as2_partners(tenant_id=0)
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
            svc = AS2PartnerService(uow=uow)
            await svc.update_as2_partner(tenant_id=0, partner_id=partner_id, cmd=cmd)
            updated_partner = await uow.as2_partners.get_as2_partner(
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
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/as2/trading-partners/{partner_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_platform_as2_partner(
    partner_id: UUID,
    uow: UnitOfWork = Depends(get_uow),
) -> None:
    """Deletes an AS2 partner."""
    async with uow:
        svc = AS2PartnerService(uow=uow)
        try:
            await svc.delete_as2_partner(tenant_id=0, partner_id=partner_id)
            await uow.commit()
        except Exception as e:
            if "IntegrityError" in str(type(e)):
                raise HTTPException(
                    status_code=400, detail="Partner is in use and cannot be deleted."
                ) from e
            raise HTTPException(status_code=500, detail=str(e)) from e
