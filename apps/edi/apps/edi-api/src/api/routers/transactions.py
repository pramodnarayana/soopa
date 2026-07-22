import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.core.uow import UnitOfWork
from api.dependencies import get_current_tenant_id, get_tenant_uow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/transactions", tags=["Transactions"])

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


# --- Endpoints ---


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
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
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                }
            )

        return TransactionListResponse(items=items)


@router.get("/thread", response_model=TransactionThreadResponse)
async def get_transaction_thread(
    key: str = Query(..., description="Business metadata key (e.g. shipment_id)"),
    value: str = Query(..., description="Business metadata value (e.g. 12345)"),
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
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
    trace_id: UUID,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> TransactionDetailResponse:
    """
    Get the full deep-dive payload for a single trace lifecycle spanning EdiMessage, EdiJson, and ApiGateway.
    """
    async with uow:
        result = await uow.transactions.get_transaction(tenant_id, trace_id)
        if not result or not result.edi_message:
            raise HTTPException(status_code=404, detail="Transaction not found")

        msg = result.edi_message
        edi_msg_dict = {
            "id": str(msg.id),
            "trace_id": str(msg.trace_id),
            "direction": msg.direction,
            "connection_type": msg.connection_type,
            "sender_id": msg.sender_id,
            "receiver_id": msg.receiver_id,
            "gs_sender_id": msg.gs_sender_id,
            "gs_receiver_id": msg.gs_receiver_id,
            "status": msg.status,
            "edi_data": msg.edi_data,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        }

        edi_jsons = []
        for j in result.edi_jsons or []:
            edi_jsons.append(
                {
                    "id": str(j.id),
                    "transaction_type": j.transaction_type,
                    "sender_id": j.sender_id,
                    "receiver_id": j.receiver_id,
                    "gs_sender_id": j.gs_sender_id,
                    "gs_receiver_id": j.gs_receiver_id,
                    "business_metadata": j.business_metadata,
                    "payload": j.payload,
                    "status": j.status,
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                }
            )

        apigws = []
        for gw in result.api_gateways or []:
            apigws.append(
                {
                    "id": str(gw.id),
                    "webhook_url": gw.webhook_url,
                    "http_status_code": gw.http_status_code,
                    "payload": gw.payload,
                    "response": gw.response,
                    "status": gw.status,
                    "created_at": gw.created_at.isoformat() if gw.created_at else None,
                }
            )

        trading_partner_name, new_conn_type = await uow.resolve_trading_partner_name(
            msg, result.edi_jsons or []
        )
        if new_conn_type and edi_msg_dict.get("connection_type") in ("UNKNOWN", None):
            edi_msg_dict["connection_type"] = new_conn_type

        return TransactionDetailResponse(
            edi_message=edi_msg_dict,
            edi_json=edi_jsons,
            api_gateway=apigws,
            trading_partner_name=trading_partner_name,
        )
