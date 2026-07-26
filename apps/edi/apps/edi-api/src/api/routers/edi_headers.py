from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from api.adapters.http.dtos import (
    CreateOutboundEdiHeaderRequest,
    UpdateOutboundEdiHeaderRequest,
)
from api.core.services.edi_header_service import EdiHeaderService
from api.core.uow import UnitOfWork
from api.dependencies.auth import get_current_tenant_id
from api.dependencies.database import get_tenant_uow
from api.domain.models import (
    UNSET,
    CreateOutboundEdiHeaderCmd,
    UpdateOutboundEdiHeaderCmd,
)

router = APIRouter(prefix="/api/v1/edi-headers", tags=["EDI Headers"])


class OutboundEdiHeaderItem(BaseModel):
    """Typed response schema for a single Outbound EDI Header entry."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    trading_partner_id: str | None = None
    isa_sender_id: str
    isa_sender_qualifier: str | None = None
    isa_receiver_id: str
    isa_receiver_qualifier: str | None = None
    gs_sender_id: str
    gs_receiver_id: str
    transaction_type: str
    default_standard: str
    default_version: str


@router.get("", response_model=list[OutboundEdiHeaderItem], status_code=status.HTTP_200_OK)
async def list_edi_headers(
    tenant_id: str = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """
    List all Outbound EDI Headers for the current Tenant.
    """
    async with uow:
        service = EdiHeaderService(uow=uow)
        headers = await service.get_outbound_edi_headers(tenant_id)
        return headers


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_edi_header(
    request: CreateOutboundEdiHeaderRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """
    Creates a new Outbound EDI Header in the Tenant Data Plane.
    """
    async with uow:
        service = EdiHeaderService(uow=uow)

        cmd = CreateOutboundEdiHeaderCmd(
            name=request.name,
            trading_partner_id=request.trading_partner_id,
            isa_sender_id=request.isa_sender_id,
            isa_sender_qualifier=request.isa_sender_qualifier,
            isa_receiver_id=request.isa_receiver_id,
            isa_receiver_qualifier=request.isa_receiver_qualifier,
            gs_sender_id=request.gs_sender_id,
            gs_receiver_id=request.gs_receiver_id,
            transaction_type=request.transaction_type,
            default_standard=request.default_standard,
            default_version=request.default_version,
        )

        header_id = await service.create_outbound_edi_header(tenant_id, cmd)
        await uow.commit()

        return {"id": header_id}


@router.patch("/{header_id}", status_code=status.HTTP_200_OK)
async def update_edi_header(
    header_id: UUID,
    request: UpdateOutboundEdiHeaderRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """
    Updates an Outbound EDI Header for the current Tenant.
    """
    async with uow:
        service = EdiHeaderService(uow=uow)

        dump = request.model_dump(exclude_unset=True)
        cmd = UpdateOutboundEdiHeaderCmd(
            name=dump.get("name", UNSET),
            trading_partner_id=dump.get("trading_partner_id", UNSET),
            isa_sender_id=dump.get("isa_sender_id", UNSET),
            isa_sender_qualifier=dump.get("isa_sender_qualifier", UNSET),
            isa_receiver_id=dump.get("isa_receiver_id", UNSET),
            isa_receiver_qualifier=dump.get("isa_receiver_qualifier", UNSET),
            gs_sender_id=dump.get("gs_sender_id", UNSET),
            gs_receiver_id=dump.get("gs_receiver_id", UNSET),
            transaction_type=dump.get("transaction_type", UNSET),
            default_standard=dump.get("default_standard", UNSET),
            default_version=dump.get("default_version", UNSET),
        )

        success = await service.update_outbound_edi_header(tenant_id, header_id, cmd)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="EDI Header not found"
            )
        await uow.commit()
    return {"status": "ok"}


@router.delete("/{header_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_edi_header(
    header_id: UUID,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> None:
    """
    Deletes an Outbound EDI Header for the current Tenant.
    """
    async with uow:
        service = EdiHeaderService(uow=uow)
        success = await service.delete_outbound_edi_header(tenant_id, header_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="EDI Header not found"
            )
        await uow.commit()
