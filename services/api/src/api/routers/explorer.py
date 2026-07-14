from typing import Any

from fastapi import APIRouter, Depends, Query
from identity.dependencies import get_current_tenant_id
from pydantic import BaseModel

from api.core.uow import UnitOfWork
from api.dependencies import get_tenant_uow

router = APIRouter(prefix="/api/v1/explorer", tags=["Explorer"])


class FilterRule(BaseModel):
    field: str
    operator: str
    value: Any


class ExplorerRequest(BaseModel):
    filters: list[FilterRule] = []


class ExplorerResponse(BaseModel):
    items: list[dict[str, Any]]


@router.post("/edi-messages", response_model=ExplorerResponse)
async def explore_edi_messages(
    req: ExplorerRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Any:
    async with uow:
        # Convert pydantic rules to list of dicts
        filters_list = [f.model_dump() for f in req.filters]
        messages = await uow.data_plane.explorer_list_edi_messages(  # type: ignore
            tenant_id=tenant_id,
            filters=filters_list,
            limit=limit,
            offset=offset,
        )

        items = []
        for msg in messages:
            items.append(
                {
                    "id": str(msg.id),
                    "trace_id": str(msg.trace_id),
                    "direction": msg.direction,
                    "transaction_type": msg.transaction_type,
                    "sender_id": msg.sender_id,
                    "receiver_id": msg.receiver_id,
                    "gs_sender_id": msg.gs_sender_id,
                    "gs_receiver_id": msg.gs_receiver_id,
                    "status": msg.status,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                    # Add important payload info (e.g., raw edi_data snippet or full)
                    "edi_data": msg.edi_data,
                    "storage_uri": msg.storage_uri,
                }
            )

        return ExplorerResponse(items=items)


@router.post("/edi-json", response_model=ExplorerResponse)
async def explore_edi_json(
    req: ExplorerRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Any:
    async with uow:
        filters_list = [f.model_dump() for f in req.filters]
        jsons = await uow.data_plane.explorer_list_edi_json(  # type: ignore
            tenant_id=tenant_id,
            filters=filters_list,
            limit=limit,
            offset=offset,
        )

        items = []
        for j in jsons:
            items.append(
                {
                    "id": str(j.id),
                    "trace_id": str(j.trace_id),
                    "direction": j.direction,
                    "transaction_type": j.transaction_type,
                    "sender_id": j.sender_id,
                    "receiver_id": j.receiver_id,
                    "gs_sender_id": j.gs_sender_id,
                    "gs_receiver_id": j.gs_receiver_id,
                    "status": j.status,
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                    "business_metadata": j.business_metadata,
                    "payload": j.payload,
                }
            )

        return ExplorerResponse(items=items)
