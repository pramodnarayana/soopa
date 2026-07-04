import logging
from typing import Any
from uuid import UUID

from database.models.control_plane import AS2Partnership
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api.adapters.http.dtos import (
    AS2PartnershipResponse,
    CreateAS2PartnershipRequest,
    UpdateAS2PartnershipRequest,
)
from api.core.uow import UnitOfWork
from api.dependencies import (
    get_uow,
)
from api.domain.models import (
    CreateAS2PartnershipCmd,
    UpdateAS2PartnershipCmd,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Platform Partners - AS2 Partnerships"])


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
            p = await uow.control_plane.get_as2_partnership(
                tenant_id=0, partnership_id=partnership_id
            )
            if not p:
                raise HTTPException(status_code=404, detail="Partnership not found")

            return AS2PartnershipResponse(
                id=str(partnership_id),
                tenant_id=0,
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
    partnership_id: UUID,
    request: UpdateAS2PartnershipRequest,
    uow: UnitOfWork = Depends(get_uow),
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
                edi_version=get_val("edi_version"),
                advanced_flags=get_val("advanced_flags"),
                active=get_val("active"),
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
