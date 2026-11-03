from collections.abc import Mapping

import structlog
from edi.application.responses import (
    ApiGatewayDTO,
    EdiJsonDTO,
    EdiMessageDTO,
)
from edi.application.use_cases.replay.bulk_replay_stage_use_case import (
    BulkReplayStageCommand,
    BulkReplayStageUseCase,
)
from edi.application.use_cases.replay.modify_and_replay_use_case import (
    ModifyAndReplayCommand,
    ModifyAndReplayUseCase,
)
from edi.application.use_cases.replay.replay_stage_use_case import (
    ReplayStageCommand,
    ReplayStageUseCase,
)
from edi.application.use_cases.replay.stage_replay_processor import (
    EdiStageReplayProcessorPort,
)
from edi.application.use_cases.routing_resolution_use_case import (
    ResolveRoutingContextQuery,
    RoutingResolutionUseCase,
)
from edi.application.use_cases.trace.get_edi_trace_lineage_use_case import (
    GetEdiTraceLineageQuery,
    GetEdiTraceLineageUseCase,
)
from edi.application.use_cases.trace.get_edi_trace_use_case import (
    GetEdiTraceQuery,
    GetEdiTraceUseCase,
)
from edi.application.use_cases.trace.list_edi_json_use_case import (
    ListEdiJsonQuery,
    ListEdiJsonUseCase,
)
from edi.application.use_cases.trace.list_edi_messages_use_case import (
    ListEdiMessagesQuery,
    ListEdiMessagesUseCase,
)
from edi.domain.transaction.enums import ReplayCheckpoint
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from strace.domain import TraceLineageItemDTO

from unified_api.adapters.inbound.http.dependencies.edi.auth import get_current_tenant_id
from unified_api.adapters.inbound.http.dependencies.edi.database import get_data_plane_uow
from unified_api.adapters.inbound.http.dependencies.edi.services import (
    get_edi_stage_replay_processors,
)
from unified_api.adapters.inbound.http.edi.error_mapper import raise_http_for_edi_error

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/edi/transactions", tags=["Transactions"])


class EdiMessageListResponse(BaseModel):
    items: list[EdiMessageDTO]


class EdiJsonListResponse(BaseModel):
    items: list[EdiJsonDTO]


class EdiTraceResponse(BaseModel):
    # edi_message is Optional: outbound replay commits EdiJson as the root record;
    # EdiMessage is created asynchronously by the transform worker.
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
    trace_id: str
    replay_trace_id: str


class BulkReplayResponse(BaseModel):
    status: str
    processed_count: int


class ModifyAndReplayRequest(BaseModel):
    modified_payload: str


class ModifyAndReplayResponse(BaseModel):
    status: str
    original_trace_id: str
    new_trace_id: str


@router.post(
    "/{trace_id}/modify-and-replay", status_code=202, response_model=ModifyAndReplayResponse
)
async def modify_and_replay_transaction(
    trace_id: str,
    request: ModifyAndReplayRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWorkPort = Depends(get_data_plane_uow),
) -> ModifyAndReplayResponse:
    actor = "USER"
    log = logger.bind(tenant_id=tenant_id, trace_id=trace_id)
    log.info("modify_and_replay_transaction.received")
    async with uow:
        use_case = ModifyAndReplayUseCase(uow)
        replay_res = await use_case.execute(
            ModifyAndReplayCommand(
                tenant_id=tenant_id,
                original_trace_id=trace_id,
                modified_payload=request.modified_payload,
                actor=actor,
            )
        )
        if replay_res.is_err:
            err = replay_res.unwrap_err()
            log.error(
                "modify_and_replay_transaction.failed",
                error_code=err.code,
                reason=err.message,
            )
            raise_http_for_edi_error(err)
        new_trace_id = replay_res.unwrap()
    log.info("modify_and_replay_transaction.accepted", new_trace_id=new_trace_id)
    return ModifyAndReplayResponse(
        status="accepted", original_trace_id=trace_id, new_trace_id=new_trace_id
    )


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
    """List EDI messages for the current tenant (Tab 1 in UI)."""
    async with uow:
        messages = await ListEdiMessagesUseCase(uow).execute(
            ListEdiMessagesQuery(
                tenant_id=tenant_id,
                limit=limit,
                offset=offset,
                partner_id=partner_id,
                transaction_type=transaction_type,
                direction=direction,
            )
        )
        return EdiMessageListResponse(items=list(messages))


@router.get("/json", response_model=EdiJsonListResponse)
async def list_edi_json(
    key: str = Query(..., description="Business metadata key (e.g. shipment_id)"),
    value: str = Query(..., description="Business metadata value (e.g. 12345)"),
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWorkPort = Depends(get_data_plane_uow),
) -> EdiJsonListResponse:
    """Get a chronological thread of EDI JSON documents sharing a business metadata key/value."""
    async with uow:
        json_records = await ListEdiJsonUseCase(uow).execute(
            ListEdiJsonQuery(tenant_id=tenant_id, key=key, value=value)
        )
        return EdiJsonListResponse(items=list(json_records))


@router.get("/{trace_id}", response_model=EdiTraceResponse)
async def get_edi_trace(
    trace_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWorkPort = Depends(get_data_plane_uow),
) -> EdiTraceResponse:
    """Get the full deep-dive trace lifecycle spanning EdiMessage, EdiJson, and ApiGateway."""
    log = logger.bind(tenant_id=tenant_id, trace_id=trace_id)
    log.info("get_edi_trace.received")

    async with uow:
        trace_res = await GetEdiTraceUseCase(uow).execute(
            GetEdiTraceQuery(tenant_id=tenant_id, trace_id=trace_id)
        )
        if trace_res.is_err:
            err = trace_res.unwrap_err()
            log.error("get_edi_trace.not_found", error_code=err.code, reason=err.message)
            raise_http_for_edi_error(err)
        result = trace_res.unwrap()

        log.info(
            "get_edi_trace.use_case_result",
            has_edi_message=result.edi_message is not None,
            edi_json_count=len(result.edi_jsons),
            api_gateway_count=len(result.api_gateways),
        )

        routing_ctx = await RoutingResolutionUseCase(uow).execute(
            ResolveRoutingContextQuery(
                tenant_id=tenant_id,
                edi_message=result.edi_message,
                edi_jsons=result.edi_jsons,
            )
        )

        return EdiTraceResponse(
            edi_message=routing_ctx.enrich_message(result.edi_message),
            edi_json=list(result.edi_jsons),
            api_gateway=list(result.api_gateways),
            trading_partner_name=routing_ctx.trading_partner_name,
        )


@router.get("/{trace_id}/lineage", response_model=list[TraceLineageItemDTO])
async def get_edi_trace_lineage(
    trace_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWorkPort = Depends(get_data_plane_uow),
) -> list[TraceLineageItemDTO]:
    """Returns the full lineage of replay attempts for a given trace."""
    log = logger.bind(tenant_id=tenant_id, trace_id=trace_id)
    log.info("get_edi_trace_lineage.received")
    async with uow:
        lineage = await GetEdiTraceLineageUseCase(uow).execute(
            GetEdiTraceLineageQuery(tenant_id=tenant_id, trace_id=trace_id)
        )
        return list(lineage)


@router.post("/{trace_id}/replay", status_code=202, response_model=ReplayResponse)
async def replay_transaction(
    trace_id: str,
    request: ReplayRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWorkPort = Depends(get_data_plane_uow),
    stage_processors: Mapping[ReplayCheckpoint, EdiStageReplayProcessorPort] = Depends(
        get_edi_stage_replay_processors
    ),
) -> ReplayResponse:
    actor = "USER"
    log = logger.bind(tenant_id=tenant_id, trace_id=trace_id, checkpoint=request.checkpoint)
    log.info("replay_transaction.received")
    async with uow:
        replay_res = await ReplayStageUseCase(uow, stage_processors).execute(
            ReplayStageCommand(
                tenant_id=tenant_id,
                trace_id=trace_id,
                checkpoint=request.checkpoint,
                actor=actor,
            )
        )
        if replay_res.is_err:
            err = replay_res.unwrap_err()
            log.error("replay_transaction.failed", error_code=err.code, reason=err.message)
            raise_http_for_edi_error(err)
        replay_trace_id = replay_res.unwrap()
    log.info("replay_transaction.accepted", replay_trace_id=replay_trace_id)
    return ReplayResponse(status="accepted", trace_id=trace_id, replay_trace_id=replay_trace_id)


@router.post("/bulk-replay", status_code=202, response_model=BulkReplayResponse)
async def bulk_replay(
    request: BulkReplayRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWorkPort = Depends(get_data_plane_uow),
    stage_processors: Mapping[ReplayCheckpoint, EdiStageReplayProcessorPort] = Depends(
        get_edi_stage_replay_processors
    ),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> BulkReplayResponse:
    actor = "USER"
    log = logger.bind(
        tenant_id=tenant_id, checkpoint=request.checkpoint, count=len(request.trace_ids)
    )
    log.info("bulk_replay_transaction.received")
    async with uow:
        bulk_res = await BulkReplayStageUseCase(uow, stage_processors).execute(
            BulkReplayStageCommand(
                tenant_id=tenant_id,
                trace_ids=tuple(request.trace_ids),
                checkpoint=request.checkpoint,
                actor=actor,
                command_key=idempotency_key,
            )
        )
        if bulk_res.is_err:
            err = bulk_res.unwrap_err()
            log.error("bulk_replay_transaction.failed", error_code=err.code, reason=err.message)
            raise_http_for_edi_error(err)
        processed = bulk_res.unwrap()

    log.info("bulk_replay_transaction.accepted", processed_count=processed)
    return BulkReplayResponse(status="accepted", processed_count=processed)
