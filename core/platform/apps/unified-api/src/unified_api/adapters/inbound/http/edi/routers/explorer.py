from typing import Literal

from edi.application.responses import EdiJsonDTO, EdiMessageDTO
from edi.application.use_cases.trace.explore_edi_stage_use_case import (
    ExploreEdiJsonQuery,
    ExploreEdiMessagesQuery,
    ExploreEdiStageUseCase,
    RawStageFilterInput,
)
from edi.domain.transaction.stage_filter import ALLOWED_STAGE_FILTER_FIELDS
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field, field_validator
from seedwork.domain.types import JsonDict, JsonValue

from unified_api.adapters.inbound.http.dependencies.edi.auth import get_current_tenant_id
from unified_api.adapters.inbound.http.dependencies.edi.database import get_data_plane_uow
from unified_api.adapters.inbound.http.edi.error_mapper import raise_http_for_edi_error

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/edi/explorer", tags=["Explorer"])

AllowedOperator = Literal["eq", "neq", "contains", "in"]


class FilterRule(BaseModel):
    field: str
    operator: AllowedOperator = "eq"
    value: JsonValue

    @field_validator("field")
    @classmethod
    def validate_field(_cls, v: str) -> str:
        if v not in ALLOWED_STAGE_FILTER_FIELDS:
            raise ValueError(
                f"Filter field '{v}' is not allowed. "
                f"Allowed fields: {sorted(ALLOWED_STAGE_FILTER_FIELDS)}"
            )
        return v


class ExplorerRequest(BaseModel):
    filters: list[FilterRule] = Field(default_factory=list)


class ExplorerResponse(BaseModel):
    items: list[JsonDict]


def _serialize_edi_message(msg: EdiMessageDTO) -> JsonDict:
    return {
        "id": str(msg.id),
        "trace_id": str(msg.trace_id),
        "direction": msg.direction,
        "transaction_type": msg.transaction_type,
        "sender_id": msg.sender_id,
        "receiver_id": msg.receiver_id,
        "gs_sender_id": msg.gs_sender_id,
        "gs_receiver_id": msg.gs_receiver_id,
        "connection_type": msg.connection_type,
        "trading_partner_id": msg.trading_partner_id,
        "status": msg.status,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
        "edi_data": msg.edi_data,
        "storage_uri": msg.storage_uri,
        "original_trace_id": msg.original_trace_id,
        "replay_count": msg.replay_count,
        "error_code": msg.error_code,
        "error_details": msg.error_details,
        "status_message": msg.status_message,
    }


def _serialize_edi_json(j: EdiJsonDTO) -> JsonDict:
    return {
        "id": str(j.id),
        "trace_id": str(j.trace_id),
        "direction": j.direction,
        "transaction_type": j.transaction_type,
        "trading_partner_id": j.trading_partner_id,
        "status": j.status,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "business_metadata": j.business_metadata,
        "payload": j.payload,
        "original_trace_id": j.original_trace_id,
        "replay_count": j.replay_count,
        "error_code": j.error_code,
        "error_details": j.error_details,
        "status_message": j.status_message,
    }


@router.post("/edi-messages", response_model=ExplorerResponse, status_code=status.HTTP_200_OK)
async def explore_edi_messages(
    req: ExplorerRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWorkPort = Depends(get_data_plane_uow),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ExplorerResponse:
    async with uow:
        result = await ExploreEdiStageUseCase(uow).explore_messages(
            ExploreEdiMessagesQuery(
                tenant_id=tenant_id,
                filters=tuple(
                    RawStageFilterInput(field=f.field, operator=f.operator, value=f.value)
                    for f in req.filters
                ),
                limit=limit,
                offset=offset,
            )
        )
        if result.is_err:
            raise_http_for_edi_error(result.unwrap_err())
        return ExplorerResponse(items=[_serialize_edi_message(msg) for msg in result.unwrap()])


@router.post("/edi-json", response_model=ExplorerResponse, status_code=status.HTTP_200_OK)
async def explore_edi_json(
    req: ExplorerRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWorkPort = Depends(get_data_plane_uow),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ExplorerResponse:
    async with uow:
        result = await ExploreEdiStageUseCase(uow).explore_json(
            ExploreEdiJsonQuery(
                tenant_id=tenant_id,
                filters=tuple(
                    RawStageFilterInput(field=f.field, operator=f.operator, value=f.value)
                    for f in req.filters
                ),
                limit=limit,
                offset=offset,
            )
        )
        if result.is_err:
            raise_http_for_edi_error(result.unwrap_err())
        return ExplorerResponse(items=[_serialize_edi_json(j) for j in result.unwrap()])
