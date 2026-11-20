"""Unit tests for ConnectionPolicy application use cases (Complete CRUD)."""

from __future__ import annotations

from collections.abc import Sequence
from types import TracebackType

import pytest
from ip.engine.application.use_cases.connections.connection_policy_use_cases import (
    DeleteConnectionPolicyCommand,
    DeleteConnectionPolicyUseCase,
    GetConnectionPolicyQuery,
    GetConnectionPolicyUseCase,
    UpsertConnectionPolicyCommand,
    UpsertConnectionPolicyUseCase,
)
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.connection.connection_policy import ConnectionPolicy
from ip.engine.domain.connection.enums import AuthType, ConnectionStatus
from ip.engine.domain.connection.events import (
    ConnectionPolicySavedEvent,
)
from ip.engine.domain.exceptions import (
    DuplicateConnectionFingerprintError,
    IpErrorCode,
    Result,
)
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
def uow() -> _FakeControlPlaneUoW:
    conn_repo = _StubConnectionRepo()
    policy_repo = _StubConnectionPolicyRepo()

    # Pre-seed a test connection
    test_conn = Connection.create(
        tenant_id="ten_ercot_01",
        app_id="vendor1_ami",
        name="Vendor 1 HES Connection",
        auth_type=AuthType.API_KEY,
        public_config={},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://api.vendor1.com",
    )
    test_conn.id = "conn_vendor1"
    conn_repo.items[test_conn.id] = test_conn

    return _FakeControlPlaneUoW(conn_repo, policy_repo)


@pytest.mark.asyncio
async def test_get_connection_policy_not_found(uow: _FakeControlPlaneUoW) -> None:
    use_case = GetConnectionPolicyUseCase(control_plane_uow=uow)

    # 1. Unknown connection
    res = await use_case.execute(
        GetConnectionPolicyQuery(tenant_id="ten_ercot_01", connection_id="conn_nonexistent")
    )
    assert res.is_err
    assert res.unwrap_err().code == IpErrorCode.CONNECTION_NOT_FOUND

    # 2. Known connection, but no policy configured
    res2 = await use_case.execute(
        GetConnectionPolicyQuery(tenant_id="ten_ercot_01", connection_id="conn_vendor1")
    )
    assert res2.is_err
    assert res2.unwrap_err().code == IpErrorCode.CONNECTION_POLICY_NOT_FOUND


@pytest.mark.asyncio
async def test_upsert_connection_policy_updates_existing_record(uow: _FakeControlPlaneUoW) -> None:
    upsert_use_case = UpsertConnectionPolicyUseCase(control_plane_uow=uow)
    get_use_case = GetConnectionPolicyUseCase(control_plane_uow=uow)

    # 1. Create a new policy for conn_vendor1
    create_cmd = UpsertConnectionPolicyCommand(
        tenant_id="ten_ercot_01",
        connection_id="conn_vendor1",
        max_query_window_days=1,
        max_entities_per_call=50,
        max_concurrency=4,
        rate_limit_rpm=120,
        supports_wildcard_queries=True,
    )
    res = await upsert_use_case.execute(create_cmd)
    assert res.is_ok
    dto = res.unwrap()
    assert dto.connection_id == "conn_vendor1"
    assert dto.max_query_window_days == 1
    assert dto.max_entities_per_call == 50
    assert dto.max_concurrency == 4
    assert dto.rate_limit_rpm == 120
    assert dto.supports_wildcard_queries is True
    assert uow.committed is True

    # Check aggregate emitted domain event
    policy = await uow.connection_policies.get_by_connection_id("ten_ercot_01", "conn_vendor1")
    assert policy is not None
    events = [e for e in policy.domain_events if isinstance(e, ConnectionPolicySavedEvent)]
    assert len(events) >= 1
    assert events[0].connection_id == "conn_vendor1"

    # 2. Retrieve via GetConnectionPolicyUseCase
    get_res = await get_use_case.execute(
        GetConnectionPolicyQuery(tenant_id="ten_ercot_01", connection_id="conn_vendor1")
    )
    assert get_res.is_ok
    assert get_res.unwrap().max_query_window_days == 1

    # 3. Update existing policy (e.g. Vendor 1 upgrades to 4-day bandwidth window)
    update_cmd = UpsertConnectionPolicyCommand(
        tenant_id="ten_ercot_01",
        connection_id="conn_vendor1",
        max_query_window_days=4,
        rate_limit_rpm=240,
    )
    update_res = await upsert_use_case.execute(update_cmd)
    assert update_res.is_ok
    updated_dto = update_res.unwrap()
    assert updated_dto.max_query_window_days == 4
    assert updated_dto.rate_limit_rpm == 240
    # Untouched attributes retained
    assert updated_dto.max_entities_per_call == 50
    assert updated_dto.max_concurrency == 4


@pytest.mark.asyncio
async def test_delete_connection_policy(uow: _FakeControlPlaneUoW) -> None:
    upsert_use_case = UpsertConnectionPolicyUseCase(control_plane_uow=uow)
    delete_use_case = DeleteConnectionPolicyUseCase(control_plane_uow=uow)
    get_use_case = GetConnectionPolicyUseCase(control_plane_uow=uow)

    # 1. Create policy
    await upsert_use_case.execute(
        UpsertConnectionPolicyCommand(
            tenant_id="ten_ercot_01",
            connection_id="conn_vendor1",
            max_query_window_days=2,
        )
    )

    # 2. Delete policy
    del_res = await delete_use_case.execute(
        DeleteConnectionPolicyCommand(tenant_id="ten_ercot_01", connection_id="conn_vendor1")
    )
    assert del_res.is_ok

    # 3. Verify get returns NOT_FOUND
    get_res = await get_use_case.execute(
        GetConnectionPolicyQuery(tenant_id="ten_ercot_01", connection_id="conn_vendor1")
    )
    assert get_res.is_err
    assert get_res.unwrap_err().code == IpErrorCode.CONNECTION_POLICY_NOT_FOUND

    # 4. Deleting already-deleted policy returns NOT_FOUND
    del_res2 = await delete_use_case.execute(
        DeleteConnectionPolicyCommand(tenant_id="ten_ercot_01", connection_id="conn_vendor1")
    )
    assert del_res2.is_err
    assert del_res2.unwrap_err().code == IpErrorCode.CONNECTION_POLICY_NOT_FOUND
