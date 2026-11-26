"""Unit tests for StitchTaskConfigs HTTP Router (FastAPI)."""

from __future__ import annotations

from types import TracebackType

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from identity.domain.identity_context import PLATFORM_TENANT_ID, IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_ip_control_plane_uow,
    require_flows_read,
    require_flows_write,
)
from ip.engine.adapters.inbound.api.routers.stitch_task_configs_router import router
from ip.engine.domain.stitch.stitch import Stitch
from ip.engine.domain.stitch.stitch_task_config import StitchTaskConfig
from ip.engine.ports.outbound.connection_entity_repository_port import (
    ConnectionEntityRepositoryPort,
)
from ip.engine.ports.outbound.connection_policy_repository_port import (
    ConnectionPolicyRepositoryPort,
)
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.mapping_spec_repository_port import (
    MappingSpecRepositoryPort,
)
from ip.engine.ports.outbound.stitch_repository_port import StitchRepositoryPort
from ip.engine.ports.outbound.stitch_task_config_repository_port import (
    StitchTaskConfigRepositoryPort,
)
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort
from ip.engine.ports.outbound.transformation_repository_port import (
    TransformationRepositoryPort,
)
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort
from ip.engine.ports.outbound.webhook_endpoint_repository_port import (
    WebhookEndpointRepositoryPort,
)


class _StubStitchRepo(StitchRepositoryPort):
    def __init__(self) -> None:
        self.items: dict[str, Stitch] = {}

    async def save(self, stitch: Stitch) -> None:
        self.items[stitch.id] = stitch

    async def get_by_id(self, *, tenant_id: str, stitch_id: str) -> Stitch | None:
        s = self.items.get(stitch_id)
        if s and (s.tenant_id == tenant_id or s.tenant_id == PLATFORM_TENANT_ID):
            return s
        return None

    async def get_by_id_global(self, *, stitch_id: str) -> Stitch | None:
        return self.items.get(stitch_id)

    async def list_by_tenant(self, *, tenant_id: str) -> list[Stitch]:
        return [
            s
            for s in self.items.values()
            if s.tenant_id == tenant_id or s.tenant_id == PLATFORM_TENANT_ID
        ]

    async def list_for_event(self, *, tenant_id: str, canonical_event_type: str) -> list[Stitch]:
        return []

    async def list_by_mapping_spec_id(
        self, *, tenant_id: str, mapping_spec_id: str
    ) -> list[Stitch]:
        return []

    async def delete(self, *, tenant_id: str, stitch_id: str) -> None:
        self.items.pop(stitch_id, None)


class _StubStitchTaskConfigRepo(StitchTaskConfigRepositoryPort):
    def __init__(self) -> None:
        self.items: dict[tuple[str, str, str], StitchTaskConfig] = {}

    async def get_by_node(
        self, tenant_id: str, stitch_id: str, node_key: str
    ) -> StitchTaskConfig | None:
        return self.items.get((tenant_id, stitch_id, node_key))

    async def list_by_stitch(self, tenant_id: str, stitch_id: str) -> list[StitchTaskConfig]:
        return [c for (t, s, _), c in self.items.items() if t == tenant_id and s == stitch_id]

    async def save(self, config: StitchTaskConfig) -> None:
        self.items[(config.tenant_id, config.stitch_id, config.node_key)] = config

    async def delete(
        self,
        tenant_id: str,
        stitch_id: str,
        node_key: str,
        config: StitchTaskConfig | None = None,
    ) -> bool:
        return self.items.pop((tenant_id, stitch_id, node_key), None) is not None


class _FakeControlPlaneUoW(IpControlPlaneUnitOfWorkPort):
    def __init__(
        self,
        stitches: _StubStitchRepo,
        stitch_task_configs: _StubStitchTaskConfigRepo,
    ) -> None:
        self.stitches = stitches
        self.stitch_task_configs = stitch_task_configs
        self.committed = False

    @property
    def connections(self) -> ConnectionRepositoryPort:
        raise NotImplementedError

    @connections.setter
    def connections(self, val: ConnectionRepositoryPort) -> None:
        pass

    @property
    def connection_policies(self) -> ConnectionPolicyRepositoryPort:
        raise NotImplementedError

    @connection_policies.setter
    def connection_policies(self, val: ConnectionPolicyRepositoryPort) -> None:
        pass

    @property
    def entities(self) -> ConnectionEntityRepositoryPort:
        raise NotImplementedError

    @entities.setter
    def entities(self, val: ConnectionEntityRepositoryPort) -> None:
        pass

    @property
    def sync_runs(self) -> SyncRunRepositoryPort:
        raise NotImplementedError

    @sync_runs.setter
    def sync_runs(self, val: SyncRunRepositoryPort) -> None:
        pass

    @property
    def transformations(self) -> TransformationRepositoryPort:
        raise NotImplementedError

    @transformations.setter
    def transformations(self, val: TransformationRepositoryPort) -> None:
        pass

    @property
    def mapping_specs(self) -> MappingSpecRepositoryPort:
        raise NotImplementedError

    @mapping_specs.setter
    def mapping_specs(self, val: MappingSpecRepositoryPort) -> None:
        pass

    @property
    def webhook_endpoints(self) -> WebhookEndpointRepositoryPort:
        raise NotImplementedError

    @webhook_endpoints.setter
    def webhook_endpoints(self, val: WebhookEndpointRepositoryPort) -> None:
        pass

    async def __aenter__(self) -> _FakeControlPlaneUoW:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass


@pytest.fixture
def test_setup() -> tuple[FastAPI, _FakeControlPlaneUoW]:
    app = FastAPI()
    app.include_router(router)

    stitch_repo = _StubStitchRepo()
    config_repo = _StubStitchTaskConfigRepo()

    # Pre-seed stitch
    stitch = Stitch(
        id="st_hes_pipeline_01",
        tenant_id="ten_01",
        workflow_id="hes_pull_pipeline",
        workflow_version=1,
        canonical_event_type="telemetry.readings.requested",
    )
    stitch_repo.items[stitch.id] = stitch

    fake_uow = _FakeControlPlaneUoW(stitch_repo, config_repo)

    mock_identity = IdentityContext(
        subject="user_admin",
        claims={"sub": "user_admin"},
        tenant_id="ten_01",
        roles=("tenant_admin",),
    )

    app.dependency_overrides[get_ip_control_plane_uow] = lambda: fake_uow
    app.dependency_overrides[require_flows_read] = lambda: mock_identity
    app.dependency_overrides[require_flows_write] = lambda: mock_identity

    return app, fake_uow


@pytest.mark.asyncio
async def test_stitch_task_configs_router_crud_lifecycle(
    test_setup: tuple[FastAPI, _FakeControlPlaneUoW],
) -> None:
    app, _uow = test_setup

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. GET node returns 404 when not configured
        res1 = await client.get(
            "/api/v1/tenants/ten_01/ip/stitches/st_hes_pipeline_01/task-configs/fetch_hes_slice"
        )
        assert res1.status_code == 404

        # 2. PUT configures node runtime policy
        payload = {
            "timeout_seconds": 180,
            "max_attempts": 6,
            "queue_name": "hes_priority_queue",
            "max_in_flight_tasks": 5,
        }
        res2 = await client.put(
            "/api/v1/tenants/ten_01/ip/stitches/st_hes_pipeline_01/task-configs/fetch_hes_slice",
            json=payload,
        )
        assert res2.status_code == 200
        body = res2.json()
        assert body["stitch_id"] == "st_hes_pipeline_01"
        assert body["node_key"] == "fetch_hes_slice"
        assert body["timeout_seconds"] == 180
        assert body["max_attempts"] == 6
        assert body["queue_name"] == "hes_priority_queue"
        assert body["max_in_flight_tasks"] == 5

        # 3. GET retrieves the node config
        res3 = await client.get(
            "/api/v1/tenants/ten_01/ip/stitches/st_hes_pipeline_01/task-configs/fetch_hes_slice"
        )
        assert res3.status_code == 200
        assert res3.json()["timeout_seconds"] == 180

        # 4. LIST returns list containing the configured node
        res4 = await client.get(
            "/api/v1/tenants/ten_01/ip/stitches/st_hes_pipeline_01/task-configs"
        )
        assert res4.status_code == 200
        assert len(res4.json()) == 1

        # 5. DELETE removes node config
        res5 = await client.delete(
            "/api/v1/tenants/ten_01/ip/stitches/st_hes_pipeline_01/task-configs/fetch_hes_slice"
        )
        assert res5.status_code == 204

        # 6. GET returns 404 after deletion
        res6 = await client.get(
            "/api/v1/tenants/ten_01/ip/stitches/st_hes_pipeline_01/task-configs/fetch_hes_slice"
        )
        assert res6.status_code == 404
