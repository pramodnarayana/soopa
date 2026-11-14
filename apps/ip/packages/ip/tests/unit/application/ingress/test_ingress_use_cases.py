"""Unit tests for Ingress application use cases."""

from __future__ import annotations

import contextlib
import typing
from collections.abc import AsyncIterator, Sequence
from types import TracebackType

import pytest
from ip.engine.application.use_cases.ingress.add_webhook_event_route_use_case import (
    AddWebhookEventRouteCommand,
    AddWebhookEventRouteUseCase,
)
from ip.engine.application.use_cases.ingress.create_webhook_endpoint_use_case import (
    CreateWebhookEndpointCommand,
    CreateWebhookEndpointUseCase,
)
from ip.engine.application.use_cases.ingress.receive_webhook_push_use_case import (
    ReceiveWebhookPushCommand,
    ReceiveWebhookPushUseCase,
)
from ip.engine.application.use_cases.ingress.rotate_webhook_secret_use_case import (
    RotateWebhookSecretCommand,
    RotateWebhookSecretUseCase,
)
from ip.engine.domain.exceptions import IpErrorCode, TenantShardNotFoundError
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.domain.webhook.endpoint import WebhookEndpoint
from ip.engine.domain.webhook.enums import PayloadSemantic, VerificationStrategy
from ip.engine.ports.outbound.uow import (
    ConnectionEntityRepositoryPort,
    ConnectionRepositoryPort,
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
    StitchRepositoryPort,
    SyncRunRepositoryPort,
    TransformationRepositoryPort,
)
from ip.engine.ports.outbound.webhook_endpoint_repository_port import (
    WebhookEndpointRepositoryPort,
)
from seedwork.domain.exceptions import Result


class _InMemoryWebhookEndpointRepo(WebhookEndpointRepositoryPort):
    def __init__(self) -> None:
        self.endpoints: dict[str, WebhookEndpoint] = {}

    async def get_by_id(self, endpoint_id: str) -> WebhookEndpoint | None:
        return self.endpoints.get(endpoint_id)

    async def get_by_slug(self, tenant_id: str, endpoint_slug: str) -> WebhookEndpoint | None:
        for ep in self.endpoints.values():
            if ep.tenant_id == tenant_id and ep.endpoint_slug == endpoint_slug:
                return ep
        return None

    async def save(self, endpoint: WebhookEndpoint) -> None:
        self.endpoints[endpoint.id] = endpoint

    async def list_by_tenant(self, tenant_id: str) -> Sequence[WebhookEndpoint]:
        return [ep for ep in self.endpoints.values() if ep.tenant_id == tenant_id]

    async def delete(self, endpoint_id: str) -> None:
        self.endpoints.pop(endpoint_id, None)


class _InMemoryInboundRecordRepo:
    def __init__(self) -> None:
        self.records: dict[str, InboundRecord] = {}

    async def save(self, record: InboundRecord) -> None:
        self.records[record.id] = record

    async def get_by_id(self, record_id: str) -> InboundRecord | None:
        return self.records.get(record_id)


class _FakeControlPlaneUoW(IpControlPlaneUnitOfWorkPort):
    connections: ConnectionRepositoryPort
    entities: ConnectionEntityRepositoryPort
    sync_runs: SyncRunRepositoryPort
    transformations: TransformationRepositoryPort
    stitches: StitchRepositoryPort
    webhook_endpoints: _InMemoryWebhookEndpointRepo

    def __init__(self) -> None:
        self.webhook_endpoints = _InMemoryWebhookEndpointRepo()

    async def __aenter__(self) -> _FakeControlPlaneUoW:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        _ = (exc_type, exc_val, exc_tb)

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _FakeDataPlaneUoW:
    inbound_records: _InMemoryInboundRecordRepo

    def __init__(self) -> None:
        self.inbound_records = _InMemoryInboundRecordRepo()

    async def __aenter__(self) -> _FakeDataPlaneUoW:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        _ = (exc_type, exc_val, exc_tb)

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _FakeDataPlaneUoWProvider(IpDataPlaneUnitOfWorkProviderPort):
    def __init__(self, dp_uow: _FakeDataPlaneUoW) -> None:
        self._dp_uow = dp_uow

    async def resolve_shard_info(
        self, tenant_id: str
    ) -> Result[tuple[str, str], TenantShardNotFoundError]:
        return Result.ok(("shard-01", "in-memory://shard-01"))

    @contextlib.asynccontextmanager
    async def get_data_plane_uow(
        self,
        tenant_id: str,
        shard_id: str,
        shard_dsn: str,
    ) -> AsyncIterator[IpDataPlaneUnitOfWorkPort]:
        _ = (tenant_id, shard_id, shard_dsn)
        yield typing.cast(IpDataPlaneUnitOfWorkPort, self._dp_uow)


@pytest.mark.asyncio
async def test_create_webhook_endpoint_use_case() -> None:
    uow = _FakeControlPlaneUoW()
    use_case = CreateWebhookEndpointUseCase(uow)

    cmd = CreateWebhookEndpointCommand(
        tenant_id="tenant_walmart",
        endpoint_slug="itron-mdm",
        name="Itron MDM Ingress",
        description="Receives AMI meter telemetry",
        verification_strategy=VerificationStrategy.SHARED_HEADER_SECRET,
    )

    res = await use_case.execute(cmd)
    assert res.is_ok
    data = res.unwrap()
    assert data.endpoint_slug == "itron-mdm"
    assert data.secret_token.startswith("whsec_")
    assert "/api/v1/ingress/tenant_walmart/itron-mdm" in data.permanent_url_path

    # Check that default wildcard route was added
    ep = await uow.webhook_endpoints.get_by_id(data.endpoint_id)
    assert ep is not None
    assert len(ep.event_routes) == 1
    assert ep.event_routes[0].event_pattern == "*"

    # Duplicate slug rejected
    dup_res = await use_case.execute(cmd)
    assert dup_res.is_err
    assert dup_res.unwrap_err().code == IpErrorCode.DUPLICATE_WEBHOOK_ENDPOINT_SLUG


@pytest.mark.asyncio
async def test_add_webhook_event_route_and_rotate_secret() -> None:
    uow = _FakeControlPlaneUoW()
    create_uc = CreateWebhookEndpointUseCase(uow)
    add_route_uc = AddWebhookEventRouteUseCase(uow)
    rotate_uc = RotateWebhookSecretUseCase(uow)

    create_res = await create_uc.execute(
        CreateWebhookEndpointCommand(
            tenant_id="tenant_walmart",
            endpoint_slug="itron-mdm",
            name="Itron MDM",
        )
    )
    endpoint_id = create_res.unwrap().endpoint_id

    # Add Command Route
    route_cmd = AddWebhookEventRouteCommand(
        tenant_id="tenant_walmart",
        endpoint_id=endpoint_id,
        event_pattern="historical_extract.request",
        payload_semantic=PayloadSemantic.COMMAND,
        target_pipeline_or_workflow_id="hes_slicer_dag",
        priority=10,
    )
    route_res = await add_route_uc.execute(route_cmd)
    assert route_res.is_ok
    assert route_res.unwrap().payload_semantic == "COMMAND"

    # Rotate Secret
    rot_res = await rotate_uc.execute(
        RotateWebhookSecretCommand(
            tenant_id="tenant_walmart",
            endpoint_id=endpoint_id,
            new_secret="whsec_rotated_999",
        )
    )
    assert rot_res.is_ok
    assert rot_res.unwrap().new_secret_token == "whsec_rotated_999"


@pytest.mark.asyncio
async def test_receive_webhook_push_data_vs_command() -> None:
    cp_uow = _FakeControlPlaneUoW()
    dp_uow = _FakeDataPlaneUoW()
    dp_provider = _FakeDataPlaneUoWProvider(dp_uow)

    create_uc = CreateWebhookEndpointUseCase(cp_uow)
    add_route_uc = AddWebhookEventRouteUseCase(cp_uow)

    create_res = await create_uc.execute(
        CreateWebhookEndpointCommand(
            tenant_id="tenant_ercot",
            endpoint_slug="itron-mdm",
            name="Itron MDM",
            primary_secret="whsec_test_secret",
            verification_strategy=VerificationStrategy.SHARED_HEADER_SECRET,
        )
    )
    endpoint_id = create_res.unwrap().endpoint_id

    # Add COMMAND route for historical_extract
    await add_route_uc.execute(
        AddWebhookEventRouteCommand(
            tenant_id="tenant_ercot",
            endpoint_id=endpoint_id,
            event_pattern="historical_extract.request",
            payload_semantic=PayloadSemantic.COMMAND,
            target_pipeline_or_workflow_id="multi_hes_dag",
            priority=10,
        )
    )

    # Add DATA route for meter_readings.batch
    await add_route_uc.execute(
        AddWebhookEventRouteCommand(
            tenant_id="tenant_ercot",
            endpoint_id=endpoint_id,
            event_pattern="meter_readings.batch",
            payload_semantic=PayloadSemantic.DATA,
            target_pipeline_or_workflow_id="cim_pipeline",
            priority=20,
        )
    )

    receive_uc = ReceiveWebhookPushUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_provider,
    )

    # 1. Test COMMAND delivery
    cmd_push = ReceiveWebhookPushCommand(
        tenant_id="tenant_ercot",
        endpoint_slug="itron-mdm",
        raw_payload=b'{"range":"2026-01-01"}',
        headers={
            "X-Webhook-Token": "whsec_test_secret",
            "X-Event-Type": "historical_extract.request",
        },
        query_params={},
    )
    res_cmd = await receive_uc.execute(cmd_push)
    assert res_cmd.is_ok
    data_cmd = res_cmd.unwrap()
    assert data_cmd.status == "ACCEPTED"
    assert data_cmd.semantic == "COMMAND"
    assert data_cmd.target_pipeline_or_workflow_id == "multi_hes_dag"

    # 2. Test DATA delivery via Tier 2 body inspection
    data_push = ReceiveWebhookPushCommand(
        tenant_id="tenant_ercot",
        endpoint_slug="itron-mdm",
        raw_payload=b'{"event_type":"meter_readings.batch","readings":[1,2,3]}',
        headers={"X-Webhook-Token": "whsec_test_secret"},
        query_params={},
    )
    res_data = await receive_uc.execute(data_push)
    assert res_data.is_ok
    data_res = res_data.unwrap()
    assert data_res.status == "ACCEPTED"
    assert data_res.semantic == "DATA"
    assert data_res.target_pipeline_or_workflow_id == "cim_pipeline"

    # Verify L1 record was saved in Data Plane
    assert len(dp_uow.inbound_records.records) == 2

    # 3. Test verification failure (wrong secret)
    bad_auth_push = ReceiveWebhookPushCommand(
        tenant_id="tenant_ercot",
        endpoint_slug="itron-mdm",
        raw_payload=b"{}",
        headers={"X-Webhook-Token": "invalid_token"},
        query_params={},
    )
    res_bad = await receive_uc.execute(bad_auth_push)
    assert res_bad.is_err
    assert res_bad.unwrap_err().code == IpErrorCode.WEBHOOK_VERIFICATION_FAILED
