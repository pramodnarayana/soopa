"""FastAPI router for Simulator Entity management (`ip.simulator_entities`) and simulated L1 webhook pushes."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, Request, Response, status
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_effective_ucp_tenant_id,
    get_ip_control_plane_uow,
    get_ip_data_plane_uow_provider,
    get_ip_global_session,
    get_receive_push_executor_factory,
    get_token_manager,
    require_flows_read,
    require_flows_write,
    require_sync_trigger,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import (
    ApiErrorHttpResponse,
    from_ip_error,
)
from ip.engine.application.use_cases.connections.token_manager_service import (
    TokenManagerService,
)
from ip.engine.application.use_cases.ingestion.receive_push_use_case import (
    ReceivePushExecutorFactory,
)
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)
from ip.solutions.connectors.sandbox.universal.dto import SimulatorEntityDTO
from ip.solutions.connectors.sandbox.universal.ports import (
    SimulatorApiProviderPort,
    SimulatorEntityReaderPort,
    SimulatorUnitOfWorkPort,
)
from ip.solutions.connectors.sandbox.universal.simulate_push_use_case import (
    SimulatedPushDeliveryStyle,
    TriggerSimulatedPushCommand,
    TriggerSimulatedPushUseCase,
)
from ip.solutions.connectors.sandbox.universal.spec import (
    DEFAULT_SIMULATED_PUSH_COUNT,
    DEFAULT_SIMULATOR_CURSOR_STEP_SECONDS,
    DEFAULT_SIMULATOR_RECORDS_PER_PULL,
    MAX_SIMULATED_PUSH_COUNT,
    MAX_SIMULATOR_CURSOR_STEP_SECONDS,
    MAX_SIMULATOR_RECORDS_PER_PULL,
    MIN_SIMULATED_PUSH_COUNT,
    MIN_SIMULATOR_CURSOR_STEP_SECONDS,
    MIN_SIMULATOR_RECORDS_PER_PULL,
    SimulatorSubmissionStatus,
    StreamVelocityMode,
)
from ip.solutions.connectors.sandbox.universal.strategies import (
    ExtractionQuery,
    PullExtractionMode,
    PushCadenceMode,
)
from ip.solutions.connectors.sandbox.universal.synthesizer import _parse_iso_cursor
from ip.solutions.connectors.sandbox.universal.use_cases import (
    CreateSimulatorEntityCommand,
    CreateSimulatorEntityUseCase,
    DeleteSimulatorEntityCommand,
    DeleteSimulatorEntityUseCase,
    ListSimulatorEntitiesQuery,
    ListSimulatorEntitiesUseCase,
    PullSimulatorRecordsCommand,
    PullSimulatorRecordsUseCase,
    UpdateSimulatorEntityCommand,
    UpdateSimulatorEntityUseCase,
)
from pydantic import BaseModel, Field
from seedwork.domain.types import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


def _get_simulator_provider(request: Request) -> SimulatorApiProviderPort[AsyncSession]:
    try:
        provider: SimulatorApiProviderPort[AsyncSession] | None = (
            request.app.state.ip_simulator_provider
        )
    except AttributeError:
        provider = None
    if provider is None:
        raise RuntimeError(
            "SimulatorApiProviderPort is not initialized on app.state.ip_simulator_provider. "
            "Register routes via register_solution_routes(app) first."
        )
    return provider


def get_simulator_uow(
    request: Request,
    global_session: Annotated[AsyncSession, Depends(get_ip_global_session)],
) -> SimulatorUnitOfWorkPort:
    """Resolves a request-scoped `SimulatorUnitOfWorkPort` bound to `GlobalSession`."""
    return _get_simulator_provider(request).create_uow(global_session)


def get_simulator_entity_reader(
    request: Request,
    global_session: Annotated[AsyncSession, Depends(get_ip_global_session)],
) -> SimulatorEntityReaderPort:
    """Resolves a request-scoped `SimulatorEntityReaderPort` bound to `GlobalSession`."""
    return _get_simulator_provider(request).get_entity_reader(global_session)


def get_create_simulator_entity_use_case(
    uow: Annotated[SimulatorUnitOfWorkPort, Depends(get_simulator_uow)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> CreateSimulatorEntityUseCase:
    """Resolves `CreateSimulatorEntityUseCase` via request-scoped DI."""
    return CreateSimulatorEntityUseCase(uow=uow, connections=cp_uow.connections)


def get_list_simulator_entities_use_case(
    uow: Annotated[SimulatorUnitOfWorkPort, Depends(get_simulator_uow)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> ListSimulatorEntitiesUseCase:
    """Resolves `ListSimulatorEntitiesUseCase` via request-scoped DI."""
    return ListSimulatorEntitiesUseCase(uow=uow, connections=cp_uow.connections)


def get_update_simulator_entity_use_case(
    uow: Annotated[SimulatorUnitOfWorkPort, Depends(get_simulator_uow)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> UpdateSimulatorEntityUseCase:
    """Resolves `UpdateSimulatorEntityUseCase` via request-scoped DI."""
    return UpdateSimulatorEntityUseCase(uow=uow, connections=cp_uow.connections)


def get_delete_simulator_entity_use_case(
    uow: Annotated[SimulatorUnitOfWorkPort, Depends(get_simulator_uow)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> DeleteSimulatorEntityUseCase:
    """Resolves `DeleteSimulatorEntityUseCase` via request-scoped DI."""
    return DeleteSimulatorEntityUseCase(uow=uow, connections=cp_uow.connections)


def get_trigger_simulated_push_use_case(
    ip_dp_uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    push_executor_factory: Annotated[
        ReceivePushExecutorFactory, Depends(get_receive_push_executor_factory)
    ],
    token_manager: Annotated[TokenManagerService, Depends(get_token_manager)],
    entity_reader: Annotated[SimulatorEntityReaderPort, Depends(get_simulator_entity_reader)],
) -> TriggerSimulatedPushUseCase:
    """Resolves `TriggerSimulatedPushUseCase` via request-scoped DI."""
    return TriggerSimulatedPushUseCase(
        data_plane_uow_provider=ip_dp_uow_provider,
        push_executor_factory=push_executor_factory,
        token_manager=token_manager,
        entity_reader=entity_reader,
    )


def get_pull_simulator_records_use_case(
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    entity_reader: Annotated[SimulatorEntityReaderPort, Depends(get_simulator_entity_reader)],
) -> PullSimulatorRecordsUseCase:
    """Resolves `PullSimulatorRecordsUseCase` via request-scoped DI."""
    return PullSimulatorRecordsUseCase(
        cp_uow=cp_uow,
        entity_reader=entity_reader,
    )


class CreateSimulatorEntityHttpRequest(BaseModel):
    """HTTP request payload to configure a new entity inside a Simulator connection."""

    entity_name: str = Field(..., min_length=1, max_length=128)
    sample_blueprint: JsonValue
    primary_key_field: str | None = Field(default=None, max_length=128)
    cursor_field: str | None = Field(default=None, max_length=128)
    push_mode: PushCadenceMode = Field(default=PushCadenceMode.RANDOM_BURST)
    push_config: dict[str, JsonValue] | None = None
    records_per_pull: int = Field(
        default=DEFAULT_SIMULATOR_RECORDS_PER_PULL,
        ge=MIN_SIMULATOR_RECORDS_PER_PULL,
        le=MAX_SIMULATOR_RECORDS_PER_PULL,
    )
    cursor_step_seconds: int = Field(
        default=DEFAULT_SIMULATOR_CURSOR_STEP_SECONDS,
        ge=MIN_SIMULATOR_CURSOR_STEP_SECONDS,
        le=MAX_SIMULATOR_CURSOR_STEP_SECONDS,
    )
    velocity_mode: StreamVelocityMode = Field(default=StreamVelocityMode.ENTITY_TRANSACTIONAL)
    chaos_policy: dict[str, JsonValue] | None = None


class UpdateSimulatorEntityHttpRequest(BaseModel):
    """HTTP request payload to update an existing entity inside a Simulator connection."""

    entity_name: str | None = Field(default=None, min_length=1, max_length=128)
    sample_blueprint: JsonValue | None = None
    primary_key_field: str | None = Field(default=None, max_length=128)
    cursor_field: str | None = Field(default=None, max_length=128)
    push_mode: PushCadenceMode | None = None
    push_config: dict[str, JsonValue] | None = None
    records_per_pull: int | None = Field(
        default=None,
        ge=MIN_SIMULATOR_RECORDS_PER_PULL,
        le=MAX_SIMULATOR_RECORDS_PER_PULL,
    )
    cursor_step_seconds: int | None = Field(
        default=None,
        ge=MIN_SIMULATOR_CURSOR_STEP_SECONDS,
        le=MAX_SIMULATOR_CURSOR_STEP_SECONDS,
    )
    velocity_mode: StreamVelocityMode | None = None
    chaos_policy: dict[str, JsonValue] | None = None


class SimulatorEntityHttpResponse(BaseModel):
    """HTTP response describing a persisted Simulator Entity."""

    id: str
    tenant_id: str
    connection_id: str
    entity_name: str
    primary_key_field: str
    cursor_field: str
    push_mode: PushCadenceMode
    push_config: dict[str, JsonValue]
    records_per_pull: int
    cursor_step_seconds: int
    velocity_mode: StreamVelocityMode
    sample_blueprint: JsonValue
    inferred_json_schema: dict[str, JsonValue]
    chaos_policy: dict[str, JsonValue]
    version: int
    created_at: str
    updated_at: str


class SimulatePushHttpRequest(BaseModel):
    """HTTP request payload to trigger a simulated webhook push for an entity stream."""

    stream_name: str = Field(..., min_length=1, max_length=128)
    count: int = Field(
        default=DEFAULT_SIMULATED_PUSH_COUNT,
        ge=MIN_SIMULATED_PUSH_COUNT,
        le=MAX_SIMULATED_PUSH_COUNT,
    )
    delivery_style: SimulatedPushDeliveryStyle = Field(
        default=SimulatedPushDeliveryStyle.FULL_PAYLOAD
    )
    correlation_id: str | None = Field(default=None, max_length=128)
    cadence_mode: PushCadenceMode | None = Field(default=None)
    cadence_config: dict[str, JsonValue] | None = Field(default=None)


class SimulatePushHttpResponse(BaseModel):
    """HTTP response returned when simulated webhook records are pushed into L1 Ingress."""

    connection_id: str
    stream_name: str
    records_pushed: int
    record_ids: list[str]
    trace_ids: list[str]
    status: SimulatorSubmissionStatus = SimulatorSubmissionStatus.ACCEPTED


class PaginatedSliceRecordHttpResponse(BaseModel):
    """Single record envelope representation inside a paginated query response."""

    record_id: str
    emitted_at: str
    cursor_value: str | None
    data: dict[str, JsonValue]


class PaginatedSlicePageInfoHttpResponse(BaseModel):
    """Pagination and continuation metadata for stream slicing."""

    next_cursor: str | None
    next_offset: int | None
    continuation_token: str | None
    has_more: bool
    total_estimated: int | None


class PaginatedSliceHttpResponse(BaseModel):
    """Standardized response envelope returned by simulator pull queries."""

    stream_name: str
    records: list[PaginatedSliceRecordHttpResponse]
    page_info: PaginatedSlicePageInfoHttpResponse


def _map_entity_response(dto: SimulatorEntityDTO) -> SimulatorEntityHttpResponse:
    return SimulatorEntityHttpResponse(
        id=dto.id,
        tenant_id=dto.tenant_id,
        connection_id=dto.connection_id,
        entity_name=dto.entity_name,
        primary_key_field=dto.primary_key_field,
        cursor_field=dto.cursor_field,
        push_mode=dto.push_mode,
        push_config=dict(dto.push_config),
        records_per_pull=dto.records_per_pull,
        cursor_step_seconds=dto.cursor_step_seconds,
        velocity_mode=dto.velocity_mode,
        sample_blueprint=dto.sample_blueprint,
        inferred_json_schema=dict(dto.inferred_json_schema),
        chaos_policy=dict(dto.chaos_policy),
        version=dto.version,
        created_at=dto.created_at.isoformat(),
        updated_at=dto.updated_at.isoformat(),
    )


router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/connections",
    tags=["Integration Platform - Sandbox Simulator"],
)


@router.post(
    "/{connection_id}/simulator/entities",
    response_model=SimulatorEntityHttpResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ApiErrorHttpResponse},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ApiErrorHttpResponse},
    },
)
async def create_simulator_entity(
    connection_id: str,
    body: CreateSimulatorEntityHttpRequest,
    _context: Annotated[IdentityContext, Depends(require_flows_write)],
    effective_tenant_id: Annotated[str, Depends(get_effective_ucp_tenant_id)],
    use_case: Annotated[
        CreateSimulatorEntityUseCase, Depends(get_create_simulator_entity_use_case)
    ],
) -> SimulatorEntityHttpResponse | Response:
    """Creates and validates a new entity inside a Simulator connection."""
    log = logger.bind(
        tenant_id=effective_tenant_id,
        connection_id=connection_id,
        entity_name=body.entity_name,
    )
    log.info("ip_create_simulator_entity_http.received")
    res = await use_case.execute(
        CreateSimulatorEntityCommand(
            tenant_id=effective_tenant_id,
            connection_id=connection_id,
            entity_name=body.entity_name,
            sample_blueprint=body.sample_blueprint,
            primary_key_field=body.primary_key_field,
            cursor_field=body.cursor_field,
            push_mode=body.push_mode,
            push_config=body.push_config,
            records_per_pull=body.records_per_pull,
            cursor_step_seconds=body.cursor_step_seconds,
            velocity_mode=body.velocity_mode,
            chaos_policy=body.chaos_policy,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        log.error(
            "ip_create_simulator_entity_http.failed",
            error_code=err.code.value,
            http_status=err.http_status,
        )
        return from_ip_error(err)
    entity = res.unwrap()
    log.info("ip_create_simulator_entity_http.completed", entity_id=entity.id)
    return _map_entity_response(entity)


@router.get(
    "/{connection_id}/simulator/entities",
    response_model=list[SimulatorEntityHttpResponse],
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ApiErrorHttpResponse},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
    },
)
async def list_simulator_entities(
    connection_id: str,
    _context: Annotated[IdentityContext, Depends(require_flows_read)],
    effective_tenant_id: Annotated[str, Depends(get_effective_ucp_tenant_id)],
    use_case: Annotated[
        ListSimulatorEntitiesUseCase, Depends(get_list_simulator_entities_use_case)
    ],
) -> list[SimulatorEntityHttpResponse] | Response:
    """Lists all entities configured inside `connection_id`."""
    log = logger.bind(
        tenant_id=effective_tenant_id,
        connection_id=connection_id,
    )
    log.info("ip_list_simulator_entities_http.received")
    res = await use_case.execute(
        ListSimulatorEntitiesQuery(tenant_id=effective_tenant_id, connection_id=connection_id)
    )
    if res.is_err:
        err = res.unwrap_err()
        log.error(
            "ip_list_simulator_entities_http.failed",
            error_code=err.code.value,
            http_status=err.http_status,
        )
        return from_ip_error(err)
    entities = res.unwrap()
    log.info("ip_list_simulator_entities_http.completed", entity_count=len(entities))
    return [_map_entity_response(ent) for ent in entities]


@router.patch(
    "/{connection_id}/simulator/entities/{entity_id}",
    response_model=SimulatorEntityHttpResponse,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ApiErrorHttpResponse},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ApiErrorHttpResponse},
    },
)
async def update_simulator_entity(
    connection_id: str,
    entity_id: str,
    body: UpdateSimulatorEntityHttpRequest,
    _context: Annotated[IdentityContext, Depends(require_flows_write)],
    effective_tenant_id: Annotated[str, Depends(get_effective_ucp_tenant_id)],
    use_case: Annotated[
        UpdateSimulatorEntityUseCase, Depends(get_update_simulator_entity_use_case)
    ],
) -> SimulatorEntityHttpResponse | Response:
    """Updates an existing entity inside `connection_id` and bumps its schema version."""
    log = logger.bind(
        tenant_id=effective_tenant_id,
        connection_id=connection_id,
        entity_id=entity_id,
    )
    log.info("ip_update_simulator_entity_http.received")
    res = await use_case.execute(
        UpdateSimulatorEntityCommand(
            tenant_id=effective_tenant_id,
            connection_id=connection_id,
            entity_id=entity_id,
            entity_name=body.entity_name,
            sample_blueprint=body.sample_blueprint,
            primary_key_field=body.primary_key_field,
            cursor_field=body.cursor_field,
            push_mode=body.push_mode,
            push_config=body.push_config,
            records_per_pull=body.records_per_pull,
            cursor_step_seconds=body.cursor_step_seconds,
            velocity_mode=body.velocity_mode,
            chaos_policy=body.chaos_policy,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        log.error(
            "ip_update_simulator_entity_http.failed",
            error_code=err.code.value,
            http_status=err.http_status,
        )
        return from_ip_error(err)
    updated = res.unwrap()
    log.info("ip_update_simulator_entity_http.completed", version=updated.version)
    return _map_entity_response(updated)


@router.delete(
    "/{connection_id}/simulator/entities/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ApiErrorHttpResponse},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
    },
)
async def delete_simulator_entity(
    connection_id: str,
    entity_id: str,
    _context: Annotated[IdentityContext, Depends(require_flows_write)],
    effective_tenant_id: Annotated[str, Depends(get_effective_ucp_tenant_id)],
    use_case: Annotated[
        DeleteSimulatorEntityUseCase, Depends(get_delete_simulator_entity_use_case)
    ],
) -> Response:
    """Deletes an entity from `connection_id`."""
    log = logger.bind(
        tenant_id=effective_tenant_id,
        connection_id=connection_id,
        entity_id=entity_id,
    )
    log.info("ip_delete_simulator_entity_http.received")
    res = await use_case.execute(
        DeleteSimulatorEntityCommand(
            tenant_id=effective_tenant_id,
            connection_id=connection_id,
            entity_id=entity_id,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        log.error(
            "ip_delete_simulator_entity_http.failed",
            error_code=err.code.value,
            http_status=err.http_status,
        )
        return from_ip_error(err)
    log.info("ip_delete_simulator_entity_http.completed")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{connection_id}/simulate-push",
    response_model=SimulatePushHttpResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ApiErrorHttpResponse},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ApiErrorHttpResponse},
    },
)
async def simulate_push(
    connection_id: str,
    body: SimulatePushHttpRequest,
    _context: Annotated[IdentityContext, Depends(require_sync_trigger)],
    effective_tenant_id: Annotated[str, Depends(get_effective_ucp_tenant_id)],
    use_case: Annotated[TriggerSimulatedPushUseCase, Depends(get_trigger_simulated_push_use_case)],
) -> SimulatePushHttpResponse | Response:
    """Synthesizes N fake records from the Simulator connection entity and pushes them into L1 Ingress."""
    log = logger.bind(
        tenant_id=effective_tenant_id,
        connection_id=connection_id,
        stream_name=body.stream_name,
        count=body.count,
        delivery_style=body.delivery_style.value,
        cadence_mode=body.cadence_mode.value if body.cadence_mode else None,
    )
    log.info("ip_simulate_push_http.received")
    res = await use_case.execute(
        TriggerSimulatedPushCommand(
            tenant_id=effective_tenant_id,
            connection_id=connection_id,
            stream_name=body.stream_name,
            count=body.count,
            delivery_style=body.delivery_style,
            correlation_id=body.correlation_id,
            cadence_mode=body.cadence_mode,
            cadence_config=body.cadence_config,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        log.error(
            "ip_simulate_push_http.failed",
            error_code=err.code.value,
            http_status=err.http_status,
        )
        return from_ip_error(err)

    dto = res.unwrap()
    log.info("ip_simulate_push_http.completed", records_pushed=dto.records_pushed)
    return SimulatePushHttpResponse(
        connection_id=dto.connection_id,
        stream_name=dto.stream_name,
        records_pushed=dto.records_pushed,
        record_ids=list(dto.record_ids),
        trace_ids=list(dto.trace_ids),
    )


@router.get(
    "/{connection_id}/simulator/streams/{stream_name}/records",
    response_model=PaginatedSliceHttpResponse,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ApiErrorHttpResponse},
        status.HTTP_401_UNAUTHORIZED: {"model": ApiErrorHttpResponse},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_429_TOO_MANY_REQUESTS: {"model": ApiErrorHttpResponse},
    },
)
async def pull_simulator_records(
    connection_id: str,
    stream_name: str,
    _context: Annotated[IdentityContext, Depends(require_flows_read)],
    effective_tenant_id: Annotated[str, Depends(get_effective_ucp_tenant_id)],
    use_case: Annotated[PullSimulatorRecordsUseCase, Depends(get_pull_simulator_records_use_case)],
    mode: PullExtractionMode = PullExtractionMode.BOUNDED_TIME_WINDOW,
    start_time: str | None = None,
    end_time: str | None = None,
    cursor: str | None = None,
    offset: int | None = None,
    limit: Annotated[
        int,
        Query(
            ge=MIN_SIMULATOR_RECORDS_PER_PULL,
            le=MAX_SIMULATOR_RECORDS_PER_PULL,
            description="Maximum records to return per page.",
        ),
    ] = DEFAULT_SIMULATOR_RECORDS_PER_PULL,
    token: str | None = None,
    since_version: int | None = None,
) -> PaginatedSliceHttpResponse | Response:
    """Extracts a slice of deterministic synthetic records from a Simulator entity stream."""
    log = logger.bind(
        tenant_id=effective_tenant_id,
        connection_id=connection_id,
        stream_name=stream_name,
        mode=mode.value,
    )
    log.info("ip_pull_simulator_records_http.received")

    parsed_start = _parse_iso_cursor(start_time) if start_time else None
    parsed_end = _parse_iso_cursor(end_time) if end_time else None

    query = ExtractionQuery(
        stream_name=stream_name,
        mode=mode,
        start_time=parsed_start,
        end_time=parsed_end,
        cursor=cursor,
        offset=offset,
        limit=limit,
        token=token,
        since_version=since_version,
    )

    res = await use_case.execute(
        PullSimulatorRecordsCommand(
            tenant_id=effective_tenant_id,
            connection_id=connection_id,
            stream_name=stream_name,
            query=query,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        log.error(
            "ip_pull_simulator_records_http.failed",
            error_code=err.code.value,
            http_status=err.http_status,
        )
        return from_ip_error(err)

    slice_dto = res.unwrap()
    log.info(
        "ip_pull_simulator_records_http.completed",
        record_count=len(slice_dto.records),
        has_more=slice_dto.has_more,
    )
    return PaginatedSliceHttpResponse(
        stream_name=stream_name,
        records=[
            PaginatedSliceRecordHttpResponse(
                record_id=r.record_id,
                emitted_at=r.emitted_at,
                cursor_value=r.cursor_value,
                data=dict(r.data),
            )
            for r in slice_dto.records
        ],
        page_info=PaginatedSlicePageInfoHttpResponse(
            next_cursor=slice_dto.next_cursor,
            next_offset=slice_dto.next_offset,
            continuation_token=slice_dto.continuation_token,
            has_more=slice_dto.has_more,
            total_estimated=slice_dto.total_estimated,
        ),
    )


__all__ = [
    "CreateSimulatorEntityHttpRequest",
    "PaginatedSliceHttpResponse",
    "PaginatedSlicePageInfoHttpResponse",
    "PaginatedSliceRecordHttpResponse",
    "SimulatePushHttpRequest",
    "SimulatePushHttpResponse",
    "SimulatorEntityHttpResponse",
    "UpdateSimulatorEntityHttpRequest",
    "get_create_simulator_entity_use_case",
    "get_delete_simulator_entity_use_case",
    "get_list_simulator_entities_use_case",
    "get_pull_simulator_records_use_case",
    "get_simulator_entity_reader",
    "get_simulator_uow",
    "get_trigger_simulated_push_use_case",
    "get_update_simulator_entity_use_case",
    "pull_simulator_records",
    "router",
]
