import structlog
from edi.adapters.outbound.database.routing_resolver_repository import (
    SqlAlchemyRoutingResolverRepository,
)
from edi.application.dtos.transactions import ApiGatewayDTO, EdiJsonDTO, EdiMessageDTO
from edi.application.use_cases.routing_resolution_use_case import RoutingResolutionUseCase
from edi.application.use_cases.transactions.bulk_replay_transactions_use_case import (
    BulkReplayTransactionsUseCase,
)
from edi.application.use_cases.transactions.get_edi_trace_use_case import (
    GetEdiTraceUseCase,
)
from edi.application.use_cases.transactions.list_edi_json_use_case import (
    ListEdiJsonUseCase,
)
from edi.application.use_cases.transactions.list_edi_messages_use_case import (
    ListEdiMessagesUseCase,
)
from edi.application.use_cases.transactions.replay_transaction_use_case import (
    ReplayTransactionUseCase,
)
from edi.domain.enums import ReplayCheckpoint
from edi.domain.exceptions import TransactionNotFoundError
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from unified_api.adapters.inbound.http.dependencies.edi.auth import get_current_tenant_id
from unified_api.adapters.inbound.http.dependencies.edi.database import (
    get_data_plane_uow,
    get_global_session,
    get_tenant_session,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/edi/transactions", tags=["Transactions"])

# --- DTOs ---


class EdiMessageListResponse(BaseModel):
    items: list[EdiMessageDTO]


class EdiJsonListResponse(BaseModel):
    items: list[EdiJsonDTO]


class EdiTraceResponse(BaseModel):
    # edi_message is Optional: outbound replay commits EdiJson as the root record;
    # EdiMessage is created asynchronously by the transform worker. The HTTP contract
    # must reflect this — a non-nullable field here causes a 500 on in-flight traces.
    edi_message: EdiMessageDTO | None = None
    edi_json: list[EdiJsonDTO]
    api_gateway: list[ApiGatewayDTO]
    trading_partner_name: str | None = None


class BulkReplayRequest(BaseModel):
    trace_ids: list[str] = Field(..., min_length=1, max_length=100)
    checkpoint: ReplayCheckpoint


class ReplayRequest(BaseModel):
    checkpoint: ReplayCheckpoint


class ReplayResponse(BaseModel):
    status: str
    trace_id: str  # original trace that was replayed
    replay_trace_id: str  # newly generated immutable trace


class BulkReplayResponse(BaseModel):
    status: str
    processed_count: int


# --- Endpoints ---


@router.get("/messages", response_model=EdiMessageListResponse)
async def list_edi_messages(
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWorkPort = Depends(get_data_plane_uow),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    partner_id: str | None = Query(None, description="Filter by sender or receiver ID"),
    transaction_type: str | None = Query(
        None, description="Filter by EDI transaction type (e.g., 850)"
    ),
    direction: str | None = Query(None, description="INBOUND or OUTBOUND"),
) -> EdiMessageListResponse:
    """
    List EDI messages for the current tenant (Tab 1 in UI).
    """
    async with uow:
        svc = ListEdiMessagesUseCase(uow)
        messages = await svc.list_edi_messages(
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
            partner_id=partner_id,
            transaction_type=transaction_type,
            direction=direction,
        )

        return EdiMessageListResponse(items=list(messages))


@router.get("/json", response_model=EdiJsonListResponse)
async def list_edi_json(
    key: str = Query(..., description="Business metadata key (e.g. shipment_id)"),
    value: str = Query(..., description="Business metadata value (e.g. 12345)"),
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWorkPort = Depends(get_data_plane_uow),
) -> EdiJsonListResponse:
    """
    Get a chronological thread of EDI JSON documents sharing a specific business metadata key/value (Tab 2 in UI).
    """
    async with uow:
        svc = ListEdiJsonUseCase(uow)
        json_records = await svc.list_edi_json(tenant_id, key, value)
        return EdiJsonListResponse(items=list(json_records))


@router.get("/{trace_id}", response_model=EdiTraceResponse)
async def get_edi_trace(
    trace_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWorkPort = Depends(get_data_plane_uow),
    global_session: AsyncSession = Depends(get_global_session),
    tenant_session: AsyncSession = Depends(get_tenant_session),
) -> EdiTraceResponse:
    """
    Get the full deep-dive trace lifecycle spanning EdiMessage, EdiJson, and ApiGateway.
    """
    log = logger.bind(tenant_id=tenant_id, trace_id=trace_id)
    log.info("get_edi_trace.received")

    resolver_repo = SqlAlchemyRoutingResolverRepository(global_session, tenant_session)
    resolver = RoutingResolutionUseCase(resolver_repo)

    async with uow:
        svc = GetEdiTraceUseCase(uow)
        try:
            result = await svc.get_edi_trace(tenant_id, trace_id, resolver)

            log.info(
                "get_edi_trace.use_case_result",
                has_edi_message=result.edi_message is not None,
                edi_json_count=len(result.edi_jsons),
                api_gateway_count=len(result.api_gateways),
            )

            trading_partner_name, _new_conn_type = await resolver.resolve_routing_context(
                result.edi_message, result.edi_jsons
            )

            return EdiTraceResponse(
                edi_message=result.edi_message,
                edi_json=result.edi_jsons,
                api_gateway=result.api_gateways,
                trading_partner_name=trading_partner_name,
            )
        except TransactionNotFoundError as e:
            log.warning("get_edi_trace.not_found", reason=str(e))
            raise HTTPException(status_code=404, detail=str(e))


@router.post("/{trace_id}/replay", status_code=202, response_model=ReplayResponse)
async def replay_transaction(
    trace_id: str,
    request: ReplayRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWorkPort = Depends(get_data_plane_uow),
) -> ReplayResponse:
    actor = "USER"  # TODO: extract from token
    log = logger.bind(tenant_id=tenant_id, trace_id=trace_id, checkpoint=request.checkpoint)
    log.info("replay_transaction.received")
    async with uow:
        try:
            use_case = ReplayTransactionUseCase(uow)
            match request.checkpoint:
                case ReplayCheckpoint.TRANSFORM:
                    replay_trace_id = await use_case.retry_transform(tenant_id, trace_id, actor)
                case ReplayCheckpoint.DELIVERY:
                    replay_trace_id = await use_case.retry_deliver(tenant_id, trace_id, actor)
        except TransactionNotFoundError as exc:
            log.warning("replay_transaction.not_found", reason=str(exc))
            raise HTTPException(status_code=404, detail=str(exc))
    log.info("replay_transaction.accepted", replay_trace_id=replay_trace_id)
    return ReplayResponse(status="accepted", trace_id=trace_id, replay_trace_id=replay_trace_id)


@router.post("/bulk-replay", status_code=202, response_model=BulkReplayResponse)
async def bulk_replay(
    request: BulkReplayRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWorkPort = Depends(get_data_plane_uow),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> BulkReplayResponse:
    actor = "USER"
    log = logger.bind(
        tenant_id=tenant_id, checkpoint=request.checkpoint, count=len(request.trace_ids)
    )
    log.info("bulk_replay_transaction.received")
    async with uow:
        try:
            use_case = BulkReplayTransactionsUseCase(uow)
            match request.checkpoint:
                case ReplayCheckpoint.TRANSFORM:
                    processed = await use_case.bulk_retry_transform(
                        tenant_id, request.trace_ids, actor, command_key=idempotency_key
                    )
                case ReplayCheckpoint.DELIVERY:
                    processed = await use_case.bulk_retry_deliver(
                        tenant_id, request.trace_ids, actor, command_key=idempotency_key
                    )
        except TransactionNotFoundError as exc:
            log.warning("bulk_replay_transaction.not_found", reason=str(exc))
            raise HTTPException(status_code=404, detail=str(exc))

    log.info("bulk_replay_transaction.accepted", processed_count=processed)
    return BulkReplayResponse(status="accepted", processed_count=processed)
