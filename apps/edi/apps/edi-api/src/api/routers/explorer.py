from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, field_validator

from api.adapters.uow_adapter import SqlAlchemyDataPlaneUnitOfWork as DataPlaneUnitOfWork
from api.dependencies.auth import get_current_tenant_id
from api.dependencies.database import get_data_plane_uow

router = APIRouter(prefix="/api/v1/explorer", tags=["Explorer"])

# ---------------------------------------------------------------------------
# Allowed filter fields and operators — enforce at the HTTP boundary so the
# repository never receives an unvalidated filter dict.
# ---------------------------------------------------------------------------
_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "trading_partner_id",
        "direction",
        "status",
        "transaction_type",
        "sender_id",
        "receiver_id",
        "gs_sender_id",
        "gs_receiver_id",
        "format_standard",
        "connection_type",
        "business_metadata.shipment_id",
        "business_metadata.purchase_order_id",
        "business_metadata.po_number",
        "business_metadata.invoice_number",
        "business_metadata.load_number",
        "business_metadata.business_reference",
    }
)
_ALLOWED_OPERATORS: frozenset[str] = frozenset({"eq", "neq", "contains", "in"})

AllowedOperator = Literal["eq", "neq", "contains", "in"]


class FilterRule(BaseModel):
    field: str
    operator: AllowedOperator = "eq"
    value: Any

    @field_validator("field")
    @classmethod
    def validate_field(_cls, v: str) -> str:
        if v not in _ALLOWED_FIELDS:
            raise ValueError(
                f"Filter field '{v}' is not allowed. Allowed fields: {sorted(_ALLOWED_FIELDS)}"
            )
        return v


class ExplorerRequest(BaseModel):
    filters: list[FilterRule] = []


class ExplorerResponse(BaseModel):
    items: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Shared serialisers — single source of truth so both endpoints produce the
# same shape for the same model type.
# ---------------------------------------------------------------------------


def _serialize_edi_message(msg: Any) -> dict[str, Any]:
    return {
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
        "edi_data": msg.edi_data,
        "storage_uri": msg.storage_uri,
    }


def _serialize_edi_json(j: Any) -> dict[str, Any]:
    return {
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/edi-messages", response_model=ExplorerResponse, status_code=status.HTTP_200_OK)
async def explore_edi_messages(
    req: ExplorerRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWork = Depends(get_data_plane_uow),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Any:
    async with uow:
        filters_list = [f.model_dump() for f in req.filters]
        messages = await uow.transactions.explorer_list_edi_messages(
            tenant_id=tenant_id,
            filters=filters_list,
            limit=limit,
            offset=offset,
        )
        return ExplorerResponse(items=[_serialize_edi_message(msg) for msg in messages])


@router.post("/edi-json", response_model=ExplorerResponse, status_code=status.HTTP_200_OK)
async def explore_edi_json(
    req: ExplorerRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWork = Depends(get_data_plane_uow),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Any:
    async with uow:
        filters_list = [f.model_dump() for f in req.filters]
        jsons = await uow.transactions.explorer_list_edi_json(
            tenant_id=tenant_id,
            filters=filters_list,
            limit=limit,
            offset=offset,
        )
        return ExplorerResponse(items=[_serialize_edi_json(j) for j in jsons])
