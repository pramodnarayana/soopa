"""Unit tests for ConnectionPolicies HTTP Router (FastAPI)."""

from __future__ import annotations

from collections.abc import Sequence
from types import TracebackType

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_ip_control_plane_uow,
    require_flows_read,
    require_flows_write,
)
from ip.engine.adapters.inbound.api.routers.connection_policies_router import router
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.connection.connection_policy import ConnectionPolicy
from ip.engine.domain.connection.enums import AuthType, ConnectionStatus
from ip.engine.domain.exceptions import DuplicateConnectionFingerprintError, Result
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


class _StubConnectionRepo(ConnectionRepositoryPort):
    def __init__(self) -> None:
        self.items: dict[str, Connection] = {}

    async def save(
        self, connection: Connection
    ) -> Result[Connection, DuplicateConnectionFingerprintError]:
        self.items[connection.id] = connection
        return Result.ok(connection)

    async def get_by_id(self, connection_id: str) -> Connection | None:
        return self.items.get(connection_id)

    async def get_by_fingerprint(self, tenant_id: str, fingerprint: str) -> Connection | None:
        return None

    async def list_by_tenant(
        self, tenant_id: str, status: ConnectionStatus | None = None
    ) -> Sequence[Connection]:
        return [c for c in self.items.values() if c.tenant_id == tenant_id]

    async def delete(self, connection: Connection) -> None:
        self.items.pop(connection.id, None)

    async def delete_by_id(self, connection_id: str) -> None:
        self.items.pop(connection_id, None)


class _StubConnectionPolicyRepo(ConnectionPolicyRepositoryPort):
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], ConnectionPolicy] = {}

    async def get_by_connection_id(
        self, tenant_id: str, connection_id: str
    ) -> ConnectionPolicy | None:
        return self.items.get((tenant_id, connection_id))

    async def get_by_id(self, tenant_id: str, policy_id: str) -> ConnectionPolicy | None:
        for p in self.items.values():
            if p.tenant_id == tenant_id and p.id == policy_id:
                return p
        return None

    async def save(self, policy: ConnectionPolicy) -> None:
        self.items[(policy.tenant_id, policy.connection_id)] = policy

    async def delete(
        self,
        tenant_id: str,
        connection_id: str,
        policy: ConnectionPolicy | None = None,
    ) -> bool:
        return self.items.pop((tenant_id, connection_id), None) is not None


class _FakeControlPlaneUoW(IpControlPlaneUnitOfWorkPort):
    def __init__(
        self,
        connections: _StubConnectionRepo,
        connection_policies: _StubConnectionPolicyRepo,
    ) -> None:
        self.connections = connections
        self.connection_policies = connection_policies
        self.committed = False

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
    def stitches(self) -> StitchRepositoryPort:
        raise NotImplementedError

    @stitches.setter
    def stitches(self, val: StitchRepositoryPort) -> None:
        pass

    @property
    def stitch_task_configs(self) -> StitchTaskConfigRepositoryPort:
        raise NotImplementedError

    @stitch_task_configs.setter
    def stitch_task_configs(self, val: StitchTaskConfigRepositoryPort) -> None:
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

    conn_repo = _StubConnectionRepo()
    policy_repo = _StubConnectionPolicyRepo()

    # Pre-seed connection
    conn = Connection.create(
        tenant_id="ten_01",
        app_id="vendor1_ami",
        name="Vendor 1 HES",
        auth_type=AuthType.API_KEY,
        public_config={},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://api.vendor1.com",
    )
    conn.id = "conn_vendor1"
    conn_repo.items[conn.id] = conn

    fake_uow = _FakeControlPlaneUoW(conn_repo, policy_repo)

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
async def test_connection_policy_router_crud_lifecycle(
    test_setup: tuple[FastAPI, _FakeControlPlaneUoW],
) -> None:
    app, _uow = test_setup

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. GET returns 404 when policy not configured
        res1 = await client.get("/api/v1/tenants/ten_01/ip/connections/conn_vendor1/policy")
        assert res1.status_code == 404

        # 2. PUT configures operational policy
        payload = {
            "max_query_window_days": 2,
            "max_entities_per_call": 150,
            "max_concurrency": 3,
            "rate_limit_rpm": 90,
            "supports_wildcard_queries": True,
            "vendor_quirks": {"retry_delay_multiplier": 1.5},
        }
        res2 = await client.put(
            "/api/v1/tenants/ten_01/ip/connections/conn_vendor1/policy", json=payload
        )
        assert res2.status_code == 200
        body = res2.json()
        assert body["connection_id"] == "conn_vendor1"
        assert body["max_query_window_days"] == 2
        assert body["max_entities_per_call"] == 150
        assert body["max_concurrency"] == 3
        assert body["rate_limit_rpm"] == 90
        assert body["supports_wildcard_queries"] is True
        assert body["vendor_quirks"]["retry_delay_multiplier"] == 1.5

        # 3. GET retrieves the configured policy
        res3 = await client.get("/api/v1/tenants/ten_01/ip/connections/conn_vendor1/policy")
        assert res3.status_code == 200
        assert res3.json()["max_query_window_days"] == 2

        # 4. PUT updates the policy (e.g. increase window to 4 days)
        res4 = await client.put(
            "/api/v1/tenants/ten_01/ip/connections/conn_vendor1/policy",
            json={"max_query_window_days": 4},
        )
        assert res4.status_code == 200
        assert res4.json()["max_query_window_days"] == 4
        assert res4.json()["max_entities_per_call"] == 150  # preserved

        # 5. DELETE removes policy
        res5 = await client.delete("/api/v1/tenants/ten_01/ip/connections/conn_vendor1/policy")
        assert res5.status_code == 204

        # 6. GET returns 404 after deletion
        res6 = await client.get("/api/v1/tenants/ten_01/ip/connections/conn_vendor1/policy")
        assert res6.status_code == 404
