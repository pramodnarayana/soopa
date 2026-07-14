from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from identity.dependencies import get_current_tenant_id
from pydantic import BaseModel

from api.core.uow import UnitOfWork
from api.dependencies import get_tenant_uow

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
        messages = await uow.data_plane.list_transactions(  # type: ignore
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
        json_records = await uow.data_plane.get_transaction_thread(tenant_id, key, value)  # type: ignore
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
        result = await uow.data_plane.get_transaction(tenant_id, trace_id)  # type: ignore
        if not result:
            raise HTTPException(status_code=404, detail="Transaction not found")

        msg = result["edi_message"]
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
        for j in result["edi_json"]:
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
        for gw in result["api_gateway"]:
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

        trading_partner_name = None

        # 1. Resolve from the actual OutboundRoute partnership used for delivery
        outbound_route_id = getattr(msg, "outbound_route_id", None)
        if outbound_route_id:
            try:
                from database.models.control_plane import AS2Partner, SFTPPartner
                from database.models.data_plane import OutboundRoute
                from sqlalchemy import select

                route = None
                if uow.tenant_session:
                    route_res = await uow.tenant_session.execute(
                        select(OutboundRoute).where(OutboundRoute.id == outbound_route_id)
                    )
                    route = route_res.scalar_one_or_none()
                if route:
                    if route.as2_partner_id:
                        res = await uow.global_session.execute(
                            select(AS2Partner.name).where(AS2Partner.id == route.as2_partner_id)
                        )
                        trading_partner_name = res.scalar_one_or_none()
                        if edi_msg_dict["connection_type"] == "UNKNOWN":
                            edi_msg_dict["connection_type"] = "AS2"
                    elif route.sftp_partner_id:
                        res = await uow.global_session.execute(
                            select(SFTPPartner.name).where(SFTPPartner.id == route.sftp_partner_id)
                        )
                        trading_partner_name = res.scalar_one_or_none()
                        if edi_msg_dict["connection_type"] == "UNKNOWN":
                            edi_msg_dict["connection_type"] = "SFTP"
            except Exception:
                pass

        # 2. Fallback to API routing metadata
        if not trading_partner_name:
            for j in result["edi_json"]:
                bm = j.business_metadata or {}
                routing = bm.get("_routing", {})
                partner_id = routing.get("trading_partner_id")
                if partner_id:
                    try:
                        import uuid

                        from database.models.control_plane import AS2Partner, SFTPPartner
                        from sqlalchemy import select

                        pid = uuid.UUID(partner_id)
                        res = await uow.global_session.execute(
                            select(AS2Partner.name).where(AS2Partner.id == pid)
                        )
                        name = res.scalar_one_or_none()
                        if name:
                            trading_partner_name = name
                            break
                        res = await uow.global_session.execute(
                            select(SFTPPartner.name).where(SFTPPartner.id == pid)
                        )
                        name = res.scalar_one_or_none()
                        if name:
                            trading_partner_name = name
                            break
                    except Exception:
                        pass

        # 3. Fallback to Webhook URL for inbound deliveries
        if not trading_partner_name and msg.direction == "INBOUND":
            try:
                from database.models.control_plane import Webhook
                from database.models.data_plane import InboundRoute
                from sqlalchemy import select

                t_type = None
                if result["edi_json"]:
                    t_type = result["edi_json"][0].transaction_type

                if uow.tenant_session:
                    stmt = select(InboundRoute).where(
                        InboundRoute.isa_sender_id == msg.sender_id,
                        InboundRoute.isa_receiver_id == msg.receiver_id,
                        InboundRoute.transaction_type == t_type,
                        InboundRoute.active.is_(True),
                    )
                    inbound_route = (await uow.tenant_session.execute(stmt)).scalar_one_or_none()

                    if inbound_route and inbound_route.webhook_id:
                        stmt2 = select(Webhook.url).where(Webhook.id == inbound_route.webhook_id)
                        webhook_url = (await uow.global_session.execute(stmt2)).scalar_one_or_none()
                        if webhook_url:
                            trading_partner_name = f"Webhook: {webhook_url}"
            except Exception:
                pass

        return TransactionDetailResponse(
            edi_message=edi_msg_dict,
            edi_json=edi_jsons,
            api_gateway=apigws,
            trading_partner_name=trading_partner_name,
        )
