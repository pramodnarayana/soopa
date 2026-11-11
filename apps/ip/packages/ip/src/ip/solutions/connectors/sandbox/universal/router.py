"""FastAPI router for triggering Universal Sandbox Simulator webhook pushes."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Response, status
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_inbound_ack,
    get_inbound_decoder,
    get_inbound_verifier,
    get_ip_control_plane_uow,
    get_ip_data_plane_uow_provider,
    get_tiered_storage,
    require_tenant_member,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import (
    ApiErrorHttpResponse,
    from_ip_error,
)
from ip.engine.ports.outbound.inbound_ack_port import InboundAckPort
from ip.engine.ports.outbound.inbound_payload_decoder_port import InboundPayloadDecoderPort
from ip.engine.ports.outbound.inbound_verifier_port import InboundVerifierPort
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)
from ip.solutions.connectors.sandbox.universal.simulate_push_use_case import (
    SimulatedPushDeliveryStyle,
    TriggerSimulatedPushCommand,
    TriggerSimulatedPushUseCase,
)
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/connections",
    tags=["Integration Platform - Sandbox Simulator"],
)


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
    status: str = "ACCEPTED"


@router.post(
    "/{connection_id}/simulate-push",
    response_model=SimulatePushHttpResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ApiErrorHttpResponse},
    },
)
async def simulate_push(
    tenant_id: str,
    connection_id: str,
    body: SimulatePushHttpRequest,
    _context: Annotated[IdentityContext, Depends(require_tenant_member)],
    ip_cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    ip_dp_uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    tiered_storage: Annotated[TieredStoragePort, Depends(get_tiered_storage)],
    verifier: Annotated[InboundVerifierPort, Depends(get_inbound_verifier)],
    decoder: Annotated[InboundPayloadDecoderPort, Depends(get_inbound_decoder)],
    ack: Annotated[InboundAckPort, Depends(get_inbound_ack)],
) -> SimulatePushHttpResponse | Response:
    """Synthesizes N fake records for a simulator entity and pushes them into L1 Ingress."""
    use_case = TriggerSimulatedPushUseCase(
        control_plane_uow=ip_cp_uow,
        data_plane_uow_provider=ip_dp_uow_provider,
        tiered_storage=tiered_storage,
        verifier=verifier,
        decoder=decoder,
        ack=ack,
    )
    res = await use_case.execute(
        TriggerSimulatedPushCommand(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name=body.stream_name,
            count=body.count,
            delivery_style=body.delivery_style,
            correlation_id=body.correlation_id,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_simulate_push.failed",
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name=body.stream_name,
            error_code=err.code.value,
        )
        return from_ip_error(err)

    dto = res.unwrap()
    return SimulatePushHttpResponse(
        connection_id=dto.connection_id,
        stream_name=dto.stream_name,
        records_pushed=dto.records_pushed,
        record_ids=list(dto.record_ids),
        trace_ids=list(dto.trace_ids),
    )


__all__ = [
    "SimulatePushHttpRequest",
    "SimulatePushHttpResponse",
    "router",
]
