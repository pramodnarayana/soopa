import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.routing_resolver_repository import SqlAlchemyRoutingResolverRepository
from edi.adapters.uow_adapter import SqlAlchemyDataPlaneUnitOfWork as DataPlaneUnitOfWork
from edi.core.exceptions import TransactionNotFoundError
from edi.core.services.routing_resolver import RoutingResolutionService
from edi.core.services.transaction_service import TransactionService
from edi.dependencies.auth import get_current_tenant_id
from edi.dependencies.database import get_data_plane_uow, get_global_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/edi/transactions", tags=["Transactions"])

# --- DTOs ---


class TransactionListResponse(BaseModel):
    items: list[dict[str, Any]]


class TransactionDetailResponse(BaseModel):
    edi_message: dict[str, Any]
    edi_json: list[dict[str, Any]]
    api_gateway: list[dict[str, Any]]
    trading_partner_name: str | None = None


class TransactionThreadResponse(BaseModel):
    items: list[dict[str, Any]]


class ReplayRequest(BaseModel):
    tier: Literal["raw", "translation", "gateway"]


class BulkReplayRequest(BaseModel):
    trace_ids: list[str] = Field(min_length=1, max_length=100)
    tier: Literal["raw", "translation", "gateway"]


# --- Endpoints ---


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWork = Depends(get_data_plane_uow),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    partner_id: str | None = Query(None, description="Filter by sender or receiver ID"),
    transaction_type: str | None = Query(
        None, description="Filter by EDI transaction type (e.g., 850)"
    ),
    direction: str | None = Query(None, description="INBOUND or OUTBOUND"),
) -> TransactionListResponse:
    """
    List EDI transactions for the current tenant.
    """
    async with uow:
        messages = await uow.transactions.list_transactions(
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
            partner_id=partner_id,
            transaction_type=transaction_type,
            direction=direction,
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
                    "status": msg.status,
                    "edi_data": msg.edi_data,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                }
            )

        return TransactionListResponse(items=items)


@router.get("/thread", response_model=TransactionThreadResponse)
async def get_transaction_thread(
    key: str = Query(..., description="Business metadata key (e.g. shipment_id)"),
    value: str = Query(..., description="Business metadata value (e.g. 12345)"),
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWork = Depends(get_data_plane_uow),
) -> TransactionThreadResponse:
    """
    Get a chronological thread of documents sharing a specific business metadata key/value.
    """
    async with uow:
        json_records = await uow.transactions.get_transaction_thread(tenant_id, key, value)
        items = []
        for r in json_records:
            items.append(
                {
                    "id": str(r.id),
                    "trace_id": str(r.trace_id),
                    "direction": r.direction,
                    "transaction_type": r.transaction_type,
                    "sender_id": r.sender_id,
                    "receiver_id": r.receiver_id,
                    "status": r.status,
                    "business_metadata": r.business_metadata,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
            )
        return TransactionThreadResponse(items=items)


@router.get("/{trace_id}", response_model=TransactionDetailResponse)
async def get_transaction(
    trace_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWork = Depends(get_data_plane_uow),
    global_session: AsyncSession = Depends(get_global_session),
) -> TransactionDetailResponse:
    """
    Get the full deep-dive payload for a single trace lifecycle spanning EdiMessage, EdiJson, and ApiGateway.
    """
    resolver_repo = SqlAlchemyRoutingResolverRepository(global_session, uow.tenant_session)
    resolver = RoutingResolutionService(resolver_repo)

    async with uow:
        svc = TransactionService(uow)
        try:
            result = await svc.get_transaction(tenant_id, trace_id, resolver)
            return TransactionDetailResponse(
                edi_message=result.edi_message,
                edi_json=result.edi_json,
                api_gateway=result.api_gateway,
                trading_partner_name=result.trading_partner_name,
            )
        except TransactionNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))


@router.post("/{trace_id}/replay", status_code=202)
async def replay_transaction(
    trace_id: str,
    request: ReplayRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWork = Depends(get_data_plane_uow),
) -> dict[str, Any]:
    """
    Trigger an asynchronous replay of a transaction at the specified tier.
    """
    async with uow:
        svc = TransactionService(uow)
        try:
            await svc.replay_transaction(tenant_id, trace_id, request.tier)
        except TransactionNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    return {"status": "accepted", "trace_id": trace_id}


from fastapi import APIRouter, Depends, Header


@router.post("/bulk-replay", status_code=202)
async def bulk_replay_transactions(
    request: BulkReplayRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWork = Depends(get_data_plane_uow),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """
    Trigger an asynchronous replay of multiple transactions at the specified tier.
    """
    async with uow:
        svc = TransactionService(uow)
        try:
            processed_count = await svc.bulk_replay_transactions(
                tenant_id, request.trace_ids, request.tier, command_key=idempotency_key
            )
        except TransactionNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    return {"status": "accepted", "processed_count": processed_count}
