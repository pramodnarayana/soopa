"""FastAPI router for Virtual Sandbox management (`ip.simulator_sandboxes` & `ip.simulator_entities`) and simulated L1 webhook pushes."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request, Response, status
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_inbound_ack,
    get_inbound_decoder,
    get_inbound_verifier,
    get_ip_data_plane_uow_provider,
    get_ip_global_session,
    get_tiered_storage,
    get_token_manager,
    require_flows_write,
    require_ip_permission,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import (
    ApiErrorHttpResponse,
    from_ip_error,
)
from ip.engine.application.use_cases.connections.token_manager_service import (
    TokenManagerService,
)
from ip.engine.domain.authorization import IpPermission
from ip.engine.ports.outbound.inbound_ack_port import InboundAckPort
from ip.engine.ports.outbound.inbound_payload_decoder_port import InboundPayloadDecoderPort
from ip.engine.ports.outbound.inbound_verifier_port import InboundVerifierPort
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort
from ip.solutions.connectors.sandbox.universal.dto import (
    SimulatorEntityDTO,
    SimulatorSandboxDTO,
)
from ip.solutions.connectors.sandbox.universal.ports import (
    SimulatorApiProviderPort,
    SimulatorSandboxReaderPort,
    SimulatorUnitOfWorkPort,
)
from ip.solutions.connectors.sandbox.universal.simulate_push_use_case import (
    SimulatedPushDeliveryStyle,
    TriggerSimulatedPushCommand,
    TriggerSimulatedPushUseCase,
)
from ip.solutions.connectors.sandbox.universal.spec import (
    SimulatorSubmissionStatus,
    StreamVelocityMode,
)
from ip.solutions.connectors.sandbox.universal.use_cases import (
    CreateSimulatorEntityCommand,
    CreateSimulatorEntityUseCase,
    CreateSimulatorSandboxCommand,
    CreateSimulatorSandboxResult,
    CreateSimulatorSandboxUseCase,
    DeleteSimulatorEntityCommand,
    DeleteSimulatorEntityUseCase,
    DeleteSimulatorSandboxCommand,
    DeleteSimulatorSandboxUseCase,
    GetSimulatorSandboxQuery,
    GetSimulatorSandboxUseCase,
    ListSimulatorEntitiesQuery,
    ListSimulatorEntitiesUseCase,
    ListSimulatorSandboxesQuery,
    ListSimulatorSandboxesUseCase,
    UpdateSimulatorEntityCommand,
    UpdateSimulatorEntityUseCase,
)
from pydantic import BaseModel, Field
from seedwork.domain.types import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

require_flows_read = require_ip_permission(IpPermission.IP_FLOWS_READ)
require_sync_trigger = require_ip_permission(IpPermission.IP_SYNC_TRIGGER)


def _resolve_ucp_tenant_id(request: Request, path_tenant_id: str) -> str:
    """Resolves canonical `ucp_tenant_id` populated by `require_tenant_member`, falling back to `path_tenant_id`."""
    try:
        resolved: str = request.state.ucp_tenant_id
    except AttributeError:
        return path_tenant_id
    return resolved


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


def get_simulator_sandbox_reader(
    request: Request,
    global_session: Annotated[AsyncSession, Depends(get_ip_global_session)],
) -> SimulatorSandboxReaderPort:
    """Resolves a request-scoped `SimulatorSandboxReaderPort` bound to `GlobalSession`."""
    return _get_simulator_provider(request).get_sandbox_reader(global_session)


class CreateSimulatorSandboxHttpRequest(BaseModel):
    """HTTP request payload to provision a new Virtual Sandbox."""

    name: str = Field(..., min_length=1, max_length=255)


class SimulatorSandboxHttpResponse(BaseModel):
    """HTTP response describing an existing Virtual Sandbox (never exposes secret API key)."""

    id: str
    tenant_id: str
    name: str
    api_key_prefix: str
    created_at: str
    updated_at: str


class CreatedSimulatorSandboxHttpResponse(SimulatorSandboxHttpResponse):
    """HTTP response returned once upon Virtual Sandbox creation with the plaintext `api_key`."""

    api_key: str


class CreateSimulatorEntityHttpRequest(BaseModel):
    """HTTP request payload to configure a new entity inside a Virtual Sandbox."""

    entity_name: str = Field(..., min_length=1, max_length=128)
    sample_blueprint: JsonValue
    primary_key_field: str | None = Field(default=None, max_length=128)
    cursor_field: str | None = Field(default=None, max_length=128)
    records_per_pull: int = Field(default=25, ge=1, le=5000)
    cursor_step_seconds: int = Field(default=60, ge=1, le=86400)
    velocity_mode: StreamVelocityMode = Field(default=StreamVelocityMode.ENTITY_TRANSACTIONAL)
    chaos_policy: dict[str, JsonValue] | None = None


class UpdateSimulatorEntityHttpRequest(BaseModel):
    """HTTP request payload to update an existing entity inside a Virtual Sandbox."""

    entity_name: str | None = Field(default=None, min_length=1, max_length=128)
    sample_blueprint: JsonValue | None = None
    primary_key_field: str | None = Field(default=None, max_length=128)
    cursor_field: str | None = Field(default=None, max_length=128)
    records_per_pull: int | None = Field(default=None, ge=1, le=5000)
    cursor_step_seconds: int | None = Field(default=None, ge=1, le=86400)
    velocity_mode: StreamVelocityMode | None = None
    chaos_policy: dict[str, JsonValue] | None = None


class SimulatorEntityHttpResponse(BaseModel):
    """HTTP response describing a persisted Simulator Entity."""

    id: str
    tenant_id: str
    sandbox_id: str
    entity_name: str
    primary_key_field: str
    cursor_field: str
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
    count: int = Field(default=5, ge=1, le=100)
    delivery_style: SimulatedPushDeliveryStyle = Field(
        default=SimulatedPushDeliveryStyle.FULL_PAYLOAD
    )
    correlation_id: str | None = Field(default=None, max_length=128)


class SimulatePushHttpResponse(BaseModel):
    """HTTP response returned when simulated webhook records are pushed into L1 Ingress."""

    connection_id: str
    stream_name: str
    records_pushed: int
    record_ids: list[str]
    trace_ids: list[str]
    status: SimulatorSubmissionStatus = SimulatorSubmissionStatus.ACCEPTED


def _map_sandbox_response(dto: SimulatorSandboxDTO) -> SimulatorSandboxHttpResponse:
    return SimulatorSandboxHttpResponse(
        id=dto.id,
        tenant_id=dto.tenant_id,
        name=dto.name,
        api_key_prefix=dto.api_key_prefix,
        created_at=dto.created_at.isoformat(),
        updated_at=dto.updated_at.isoformat(),
    )


def _map_created_sandbox_response(
    result: CreateSimulatorSandboxResult,
) -> CreatedSimulatorSandboxHttpResponse:
    sbx = result.sandbox
    return CreatedSimulatorSandboxHttpResponse(
        id=sbx.id,
        tenant_id=sbx.tenant_id,
        name=sbx.name,
        api_key_prefix=sbx.api_key_prefix,
        api_key=result.api_key,
        created_at=sbx.created_at.isoformat(),
        updated_at=sbx.updated_at.isoformat(),
    )


def _map_entity_response(dto: SimulatorEntityDTO) -> SimulatorEntityHttpResponse:
    return SimulatorEntityHttpResponse(
        id=dto.id,
        tenant_id=dto.tenant_id,
        sandbox_id=dto.sandbox_id,
        entity_name=dto.entity_name,
        primary_key_field=dto.primary_key_field,
        cursor_field=dto.cursor_field,
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


sandbox_router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/simulator/sandboxes",
    tags=["Integration Platform - Sandbox Simulator"],
)

push_router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/connections",
    tags=["Integration Platform - Sandbox Simulator"],
)


@sandbox_router.post(
    "",
    response_model=CreatedSimulatorSandboxHttpResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ApiErrorHttpResponse},
    },
)
async def create_simulator_sandbox(
    tenant_id: str,
    request: Request,
    body: CreateSimulatorSandboxHttpRequest,
    _context: Annotated[IdentityContext, Depends(require_flows_write)],
    uow: Annotated[SimulatorUnitOfWorkPort, Depends(get_simulator_uow)],
) -> CreatedSimulatorSandboxHttpResponse | Response:
    """Provisions a new Virtual Sandbox and returns its one-time secret `api_key`."""
    effective_tenant_id = _resolve_ucp_tenant_id(request, tenant_id)
    log = logger.bind(
        tenant_id=effective_tenant_id,
        path_tenant_id=tenant_id,
        sandbox_name=body.name,
    )
    log.info("ip_create_simulator_sandbox_http.received")
    res = await CreateSimulatorSandboxUseCase(uow=uow).execute(
        CreateSimulatorSandboxCommand(tenant_id=effective_tenant_id, name=body.name)
    )
    if res.is_err:
        err = res.unwrap_err()
        log.error(
            "ip_create_simulator_sandbox_http.failed",
            error_code=err.code.value,
            http_status=err.http_status,
        )
        return from_ip_error(err)
    created = res.unwrap()
    log.info("ip_create_simulator_sandbox_http.completed", sandbox_id=created.sandbox.id)
    return _map_created_sandbox_response(created)


@sandbox_router.get(
    "",
    response_model=list[SimulatorSandboxHttpResponse],
    status_code=status.HTTP_200_OK,
)
async def list_simulator_sandboxes(
    tenant_id: str,
    request: Request,
    _context: Annotated[IdentityContext, Depends(require_flows_read)],
    uow: Annotated[SimulatorUnitOfWorkPort, Depends(get_simulator_uow)],
) -> list[SimulatorSandboxHttpResponse]:
    """Lists all Virtual Sandboxes owned by `tenant_id`."""
    effective_tenant_id = _resolve_ucp_tenant_id(request, tenant_id)
    log = logger.bind(tenant_id=effective_tenant_id, path_tenant_id=tenant_id)
    log.info("ip_list_simulator_sandboxes_http.received")
    sandboxes = await ListSimulatorSandboxesUseCase(uow=uow).execute(
        ListSimulatorSandboxesQuery(tenant_id=effective_tenant_id)
    )
    log.info("ip_list_simulator_sandboxes_http.completed", sandbox_count=len(sandboxes))
    return [_map_sandbox_response(sbx) for sbx in sandboxes]


@sandbox_router.get(
    "/{sandbox_id}",
    response_model=SimulatorSandboxHttpResponse,
    status_code=status.HTTP_200_OK,
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse}},
)
async def get_simulator_sandbox(
    tenant_id: str,
    sandbox_id: str,
    request: Request,
    _context: Annotated[IdentityContext, Depends(require_flows_read)],
    uow: Annotated[SimulatorUnitOfWorkPort, Depends(get_simulator_uow)],
) -> SimulatorSandboxHttpResponse | Response:
    """Fetches a single Virtual Sandbox scoped to `tenant_id`."""
    effective_tenant_id = _resolve_ucp_tenant_id(request, tenant_id)
    log = logger.bind(
        tenant_id=effective_tenant_id,
        path_tenant_id=tenant_id,
        sandbox_id=sandbox_id,
    )
    log.info("ip_get_simulator_sandbox_http.received")
    res = await GetSimulatorSandboxUseCase(uow=uow).execute(
        GetSimulatorSandboxQuery(tenant_id=effective_tenant_id, sandbox_id=sandbox_id)
    )
    if res.is_err:
        err = res.unwrap_err()
        log.error(
            "ip_get_simulator_sandbox_http.failed",
            error_code=err.code.value,
            http_status=err.http_status,
        )
        return from_ip_error(err)
    log.info("ip_get_simulator_sandbox_http.completed")
    return _map_sandbox_response(res.unwrap())


@sandbox_router.delete(
    "/{sandbox_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse}},
)
async def delete_simulator_sandbox(
    tenant_id: str,
    sandbox_id: str,
    request: Request,
    _context: Annotated[IdentityContext, Depends(require_flows_write)],
    uow: Annotated[SimulatorUnitOfWorkPort, Depends(get_simulator_uow)],
) -> Response:
    """Deletes a Virtual Sandbox and cascades to its `ip.simulator_entities`."""
    effective_tenant_id = _resolve_ucp_tenant_id(request, tenant_id)
    log = logger.bind(
        tenant_id=effective_tenant_id,
        path_tenant_id=tenant_id,
        sandbox_id=sandbox_id,
    )
    log.info("ip_delete_simulator_sandbox_http.received")
    res = await DeleteSimulatorSandboxUseCase(uow=uow).execute(
        DeleteSimulatorSandboxCommand(tenant_id=effective_tenant_id, sandbox_id=sandbox_id)
    )
    if res.is_err:
        err = res.unwrap_err()
        log.error(
            "ip_delete_simulator_sandbox_http.failed",
            error_code=err.code.value,
            http_status=err.http_status,
        )
        return from_ip_error(err)
    log.info("ip_delete_simulator_sandbox_http.completed")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@sandbox_router.post(
    "/{sandbox_id}/entities",
    response_model=SimulatorEntityHttpResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ApiErrorHttpResponse},
    },
)
async def create_simulator_entity(
    tenant_id: str,
    sandbox_id: str,
    request: Request,
    body: CreateSimulatorEntityHttpRequest,
    _context: Annotated[IdentityContext, Depends(require_flows_write)],
    uow: Annotated[SimulatorUnitOfWorkPort, Depends(get_simulator_uow)],
) -> SimulatorEntityHttpResponse | Response:
    """Creates and validates a new entity inside a Virtual Sandbox."""
    effective_tenant_id = _resolve_ucp_tenant_id(request, tenant_id)
    log = logger.bind(
        tenant_id=effective_tenant_id,
        path_tenant_id=tenant_id,
        sandbox_id=sandbox_id,
        entity_name=body.entity_name,
    )
    log.info("ip_create_simulator_entity_http.received")
    res = await CreateSimulatorEntityUseCase(uow=uow).execute(
        CreateSimulatorEntityCommand(
            tenant_id=effective_tenant_id,
            sandbox_id=sandbox_id,
            entity_name=body.entity_name,
            sample_blueprint=body.sample_blueprint,
            primary_key_field=body.primary_key_field,
            cursor_field=body.cursor_field,
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


@sandbox_router.get(
    "/{sandbox_id}/entities",
    response_model=list[SimulatorEntityHttpResponse],
    status_code=status.HTTP_200_OK,
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse}},
)
async def list_simulator_entities(
    tenant_id: str,
    sandbox_id: str,
    request: Request,
    _context: Annotated[IdentityContext, Depends(require_flows_read)],
    uow: Annotated[SimulatorUnitOfWorkPort, Depends(get_simulator_uow)],
) -> list[SimulatorEntityHttpResponse] | Response:
    """Lists all entities configured inside `sandbox_id`."""
    effective_tenant_id = _resolve_ucp_tenant_id(request, tenant_id)
    log = logger.bind(
        tenant_id=effective_tenant_id,
        path_tenant_id=tenant_id,
        sandbox_id=sandbox_id,
    )
    log.info("ip_list_simulator_entities_http.received")
    res = await ListSimulatorEntitiesUseCase(uow=uow).execute(
        ListSimulatorEntitiesQuery(tenant_id=effective_tenant_id, sandbox_id=sandbox_id)
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


@sandbox_router.patch(
    "/{sandbox_id}/entities/{entity_id}",
    response_model=SimulatorEntityHttpResponse,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ApiErrorHttpResponse},
    },
)
async def update_simulator_entity(
    tenant_id: str,
    sandbox_id: str,
    entity_id: str,
    request: Request,
    body: UpdateSimulatorEntityHttpRequest,
    _context: Annotated[IdentityContext, Depends(require_flows_write)],
    uow: Annotated[SimulatorUnitOfWorkPort, Depends(get_simulator_uow)],
) -> SimulatorEntityHttpResponse | Response:
    """Updates an existing entity inside `sandbox_id` and bumps its schema version."""
    effective_tenant_id = _resolve_ucp_tenant_id(request, tenant_id)
    log = logger.bind(
        tenant_id=effective_tenant_id,
        path_tenant_id=tenant_id,
        sandbox_id=sandbox_id,
        entity_id=entity_id,
    )
    log.info("ip_update_simulator_entity_http.received")
    res = await UpdateSimulatorEntityUseCase(uow=uow).execute(
        UpdateSimulatorEntityCommand(
            tenant_id=effective_tenant_id,
            sandbox_id=sandbox_id,
            entity_id=entity_id,
            entity_name=body.entity_name,
            sample_blueprint=body.sample_blueprint,
            primary_key_field=body.primary_key_field,
            cursor_field=body.cursor_field,
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


@sandbox_router.delete(
    "/{sandbox_id}/entities/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse}},
)
async def delete_simulator_entity(
    tenant_id: str,
    sandbox_id: str,
    entity_id: str,
    request: Request,
    _context: Annotated[IdentityContext, Depends(require_flows_write)],
    uow: Annotated[SimulatorUnitOfWorkPort, Depends(get_simulator_uow)],
) -> Response:
    """Deletes an entity from `sandbox_id`."""
    effective_tenant_id = _resolve_ucp_tenant_id(request, tenant_id)
    log = logger.bind(
        tenant_id=effective_tenant_id,
        path_tenant_id=tenant_id,
        sandbox_id=sandbox_id,
        entity_id=entity_id,
    )
    log.info("ip_delete_simulator_entity_http.received")
    res = await DeleteSimulatorEntityUseCase(uow=uow).execute(
        DeleteSimulatorEntityCommand(
            tenant_id=effective_tenant_id,
            sandbox_id=sandbox_id,
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


@push_router.post(
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
    tenant_id: str,
    connection_id: str,
    request: Request,
    body: SimulatePushHttpRequest,
    _context: Annotated[IdentityContext, Depends(require_sync_trigger)],
    ip_dp_uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    tiered_storage: Annotated[TieredStoragePort, Depends(get_tiered_storage)],
    verifier: Annotated[InboundVerifierPort, Depends(get_inbound_verifier)],
    decoder: Annotated[InboundPayloadDecoderPort, Depends(get_inbound_decoder)],
    ack: Annotated[InboundAckPort, Depends(get_inbound_ack)],
    token_manager: Annotated[TokenManagerService, Depends(get_token_manager)],
    sandbox_reader: Annotated[SimulatorSandboxReaderPort, Depends(get_simulator_sandbox_reader)],
) -> SimulatePushHttpResponse | Response:
    """Synthesizes N fake records from the Virtual Sandbox entity and pushes them into L1 Ingress."""
    effective_tenant_id = _resolve_ucp_tenant_id(request, tenant_id)
    log = logger.bind(
        tenant_id=effective_tenant_id,
        path_tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name=body.stream_name,
        count=body.count,
        delivery_style=body.delivery_style.value,
    )
    log.info("ip_simulate_push_http.received")
    use_case = TriggerSimulatedPushUseCase(
        data_plane_uow_provider=ip_dp_uow_provider,
        tiered_storage=tiered_storage,
        verifier=verifier,
        decoder=decoder,
        ack=ack,
        token_manager=token_manager,
        sandbox_reader=sandbox_reader,
    )
    res = await use_case.execute(
        TriggerSimulatedPushCommand(
            tenant_id=effective_tenant_id,
            connection_id=connection_id,
            stream_name=body.stream_name,
            count=body.count,
            delivery_style=body.delivery_style,
            correlation_id=body.correlation_id,
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


router = APIRouter()
router.include_router(sandbox_router)
router.include_router(push_router)

__all__ = [
    "CreateSimulatorEntityHttpRequest",
    "CreateSimulatorSandboxHttpRequest",
    "CreatedSimulatorSandboxHttpResponse",
    "SimulatePushHttpRequest",
    "SimulatePushHttpResponse",
    "SimulatorEntityHttpResponse",
    "SimulatorSandboxHttpResponse",
    "UpdateSimulatorEntityHttpRequest",
    "get_simulator_sandbox_reader",
    "get_simulator_uow",
    "router",
]
