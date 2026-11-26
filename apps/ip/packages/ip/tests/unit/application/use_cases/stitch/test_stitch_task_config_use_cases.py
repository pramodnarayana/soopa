"""Unit tests for StitchTaskConfig application use cases (Complete CRUD)."""

from __future__ import annotations

from types import TracebackType

import pytest
from identity.domain.identity_context import PLATFORM_TENANT_ID
from ip.engine.application.use_cases.stitch.stitch_task_config_use_cases import (
    DeleteStitchTaskConfigCommand,
    DeleteStitchTaskConfigUseCase,
    GetStitchTaskConfigQuery,
    GetStitchTaskConfigUseCase,
    ListStitchTaskConfigsQuery,
    ListStitchTaskConfigsUseCase,
    UpsertStitchTaskConfigCommand,
    UpsertStitchTaskConfigUseCase,
)
from ip.engine.domain.exceptions import IpErrorCode
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
def uow() -> _FakeControlPlaneUoW:
    stitch_repo = _StubStitchRepo()
    task_config_repo = _StubStitchTaskConfigRepo()

    # Pre-seed a test stitch
    test_stitch = Stitch(
        id="st_hes_pipeline_01",
        tenant_id="ten_ercot_01",
        workflow_id="hes_pull_pipeline",
        workflow_version=1,
        canonical_event_type="telemetry.readings.requested",
    )
    stitch_repo.items[test_stitch.id] = test_stitch

    return _FakeControlPlaneUoW(stitch_repo, task_config_repo)


@pytest.mark.asyncio
async def test_get_stitch_task_config_not_found(uow: _FakeControlPlaneUoW) -> None:
    use_case = GetStitchTaskConfigUseCase(control_plane_uow=uow)

    # 1. Unknown stitch
    res = await use_case.execute(
        GetStitchTaskConfigQuery(
            tenant_id="ten_ercot_01",
            stitch_id="st_unknown",
            node_key="fetch_hes_slice",
        )
    )
    assert res.is_err
    assert res.unwrap_err().code == IpErrorCode.STITCH_NOT_FOUND

    # 2. Known stitch, unconfigured node
    res2 = await use_case.execute(
        GetStitchTaskConfigQuery(
            tenant_id="ten_ercot_01",
            stitch_id="st_hes_pipeline_01",
            node_key="unconfigured_node",
        )
    )
    assert res2.is_err
    assert res2.unwrap_err().code == IpErrorCode.STITCH_TASK_CONFIG_NOT_FOUND


@pytest.mark.asyncio
async def test_upsert_persists_stitch_task_config(uow: _FakeControlPlaneUoW) -> None:
    upsert_use_case = UpsertStitchTaskConfigUseCase(control_plane_uow=uow)
    get_use_case = GetStitchTaskConfigUseCase(control_plane_uow=uow)
    list_use_case = ListStitchTaskConfigsUseCase(control_plane_uow=uow)

    # 1. Create config for node 'fetch_hes_slice'
    create_cmd = UpsertStitchTaskConfigCommand(
        tenant_id="ten_ercot_01",
        stitch_id="st_hes_pipeline_01",
        node_key="fetch_hes_slice",
        timeout_seconds=120,
        max_attempts=8,
        queue_name="hes_pull_heavy",
        max_in_flight_tasks=5,
    )
    res = await upsert_use_case.execute(create_cmd)
    assert res.is_ok
    dto = res.unwrap()
    assert dto.node_key == "fetch_hes_slice"
    assert dto.timeout_seconds == 120
    assert dto.max_attempts == 8
    assert dto.queue_name == "hes_pull_heavy"
    assert dto.max_in_flight_tasks == 5
    assert uow.committed is True

    # 2. Retrieve via GetStitchTaskConfigUseCase
    get_res = await get_use_case.execute(
        GetStitchTaskConfigQuery(
            tenant_id="ten_ercot_01",
            stitch_id="st_hes_pipeline_01",
            node_key="fetch_hes_slice",
        )
    )
    assert get_res.is_ok
    assert get_res.unwrap().timeout_seconds == 120

    # 3. Create second config for node 'push_to_mdm_kafka'
    await upsert_use_case.execute(
        UpsertStitchTaskConfigCommand(
            tenant_id="ten_ercot_01",
            stitch_id="st_hes_pipeline_01",
            node_key="push_to_mdm_kafka",
            timeout_seconds=30,
        )
    )

    # 4. List configs for stitch
    list_res = await list_use_case.execute(
        ListStitchTaskConfigsQuery(
            tenant_id="ten_ercot_01",
            stitch_id="st_hes_pipeline_01",
        )
    )
    assert list_res.is_ok
    configs = list_res.unwrap()
    assert len(configs) == 2


@pytest.mark.asyncio
async def test_delete_stitch_task_config(uow: _FakeControlPlaneUoW) -> None:
    upsert_use_case = UpsertStitchTaskConfigUseCase(control_plane_uow=uow)
    delete_use_case = DeleteStitchTaskConfigUseCase(control_plane_uow=uow)
    get_use_case = GetStitchTaskConfigUseCase(control_plane_uow=uow)

    # 1. Create config
    await upsert_use_case.execute(
        UpsertStitchTaskConfigCommand(
            tenant_id="ten_ercot_01",
            stitch_id="st_hes_pipeline_01",
            node_key="fetch_hes_slice",
        )
    )

    # 2. Delete config
    del_res = await delete_use_case.execute(
        DeleteStitchTaskConfigCommand(
            tenant_id="ten_ercot_01",
            stitch_id="st_hes_pipeline_01",
            node_key="fetch_hes_slice",
        )
    )
    assert del_res.is_ok

    # 3. Get after delete returns NOT_FOUND
    get_res = await get_use_case.execute(
        GetStitchTaskConfigQuery(
            tenant_id="ten_ercot_01",
            stitch_id="st_hes_pipeline_01",
            node_key="fetch_hes_slice",
        )
    )
    assert get_res.is_err
    assert get_res.unwrap_err().code == IpErrorCode.STITCH_TASK_CONFIG_NOT_FOUND
