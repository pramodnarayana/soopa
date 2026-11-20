"""Unit tests for MappingSpec deletion and referential integrity guards."""

from __future__ import annotations

from types import TracebackType

import pytest
from ip.engine.application.use_cases.mapping.mapping_spec_use_cases import (
    DeleteMappingSpecCommand,
    DeleteMappingSpecUseCase,
)
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.exceptions import (
    DuplicateConnectionFingerprintError,
    IpErrorCode,
    Result,
)
from ip.engine.domain.mapping import MappingRule, MappingRuleType, MappingSpec
from ip.engine.domain.stitch.stitch import Stitch
from ip.engine.ports.outbound.connection_entity_repository_port import (
    ConnectionEntityRepositoryPort,
)
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.mapping_spec_repository_port import (
    MappingSpecRepositoryPort,
)
from ip.engine.ports.outbound.stitch_repository_port import StitchRepositoryPort
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

    async def list_by_tenant(self, tenant_id: str) -> list[Connection]:
        return [c for c in self.items.values() if c.tenant_id == tenant_id]

    async def delete(self, connection_id: str) -> None:
        self.items.pop(connection_id, None)


class _StubMappingSpecRepo(MappingSpecRepositoryPort):
    def __init__(self) -> None:
        self.items: dict[str, MappingSpec] = {}

    async def save(self, spec: MappingSpec) -> None:
        self.items[spec.id] = spec

    async def get_by_id(self, *, tenant_id: str, mapping_spec_id: str) -> MappingSpec | None:
        spec = self.items.get(mapping_spec_id)
        if spec and spec.tenant_id == tenant_id:
            return spec
        return None

    async def get_latest_by_target(
        self, *, tenant_id: str, target_connection_id: str, target_entity_name: str
    ) -> MappingSpec | None:
        return None

    async def list_by_tenant(
        self,
        *,
        tenant_id: str,
        source_type: str | None = None,
        target_connection_id: str | None = None,
    ) -> list[MappingSpec]:
        return [s for s in self.items.values() if s.tenant_id == tenant_id]

    async def delete(self, *, tenant_id: str, mapping_spec_id: str) -> None:
        if mapping_spec_id in self.items and self.items[mapping_spec_id].tenant_id == tenant_id:
            del self.items[mapping_spec_id]


class _StubStitchRepo(StitchRepositoryPort):
    def __init__(self) -> None:
        self.items: dict[str, Stitch] = {}

    async def save(self, stitch: Stitch) -> None:
        self.items[stitch.id] = stitch

    async def get_by_id(self, *, tenant_id: str, stitch_id: str) -> Stitch | None:
        s = self.items.get(stitch_id)
        if s and (s.tenant_id == tenant_id or s.tenant_id == "*"):
            return s
        return None

    async def get_by_id_global(self, *, stitch_id: str) -> Stitch | None:
        return self.items.get(stitch_id)

    async def list_by_tenant(self, *, tenant_id: str) -> list[Stitch]:
        return [s for s in self.items.values() if s.tenant_id in (tenant_id, "*")]

    async def list_for_event(self, *, tenant_id: str, canonical_event_type: str) -> list[Stitch]:
        return [
            s
            for s in self.items.values()
            if s.canonical_event_type == canonical_event_type and s.is_active
        ]

    async def list_by_mapping_spec_id(
        self, *, tenant_id: str, mapping_spec_id: str
    ) -> list[Stitch]:
        return [
            s
            for s in self.items.values()
            if s.tenant_id in (tenant_id, "*") and s.mapping_spec_id == mapping_spec_id
        ]

    async def delete(self, *, tenant_id: str, stitch_id: str) -> None:
        if stitch_id in self.items:
            del self.items[stitch_id]


class _StubControlPlaneUoW(IpControlPlaneUnitOfWorkPort):
    def __init__(self) -> None:
        self.connections = _StubConnectionRepo()
        self.mapping_specs = _StubMappingSpecRepo()
        self.stitches = _StubStitchRepo()
        self.committed = False

    @property
    def entities(self) -> ConnectionEntityRepositoryPort:
        raise NotImplementedError

    @property
    def sync_runs(self) -> SyncRunRepositoryPort:
        raise NotImplementedError

    @property
    def transformations(self) -> TransformationRepositoryPort:
        raise NotImplementedError

    @property
    def webhook_endpoints(self) -> WebhookEndpointRepositoryPort:
        raise NotImplementedError

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass

    async def __aenter__(self) -> _StubControlPlaneUoW:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass


@pytest.mark.asyncio
async def test_delete_mapping_spec_success() -> None:
    uow = _StubControlPlaneUoW()
    spec = MappingSpec(
        id="fmap_test_1",
        tenant_id="tenant_alpha",
        name="Telemetry to Kafka",
        source_type="canonical.device.reading",
        target_connection_id="conn_kafka",
        target_entity_name="readings_topic",
        rules=(MappingRule(target_field="id", rule_type=MappingRuleType.DIRECT),),
    )
    await uow.mapping_specs.save(spec)

    use_case = DeleteMappingSpecUseCase(uow=uow)
    res = await use_case.execute(
        DeleteMappingSpecCommand(tenant_id="tenant_alpha", mapping_spec_id="fmap_test_1")
    )

    assert res.is_ok
    assert (
        await uow.mapping_specs.get_by_id(tenant_id="tenant_alpha", mapping_spec_id="fmap_test_1")
        is None
    )
    assert uow.committed


@pytest.mark.asyncio
async def test_delete_mapping_spec_not_found() -> None:
    uow = _StubControlPlaneUoW()
    use_case = DeleteMappingSpecUseCase(uow=uow)
    res = await use_case.execute(
        DeleteMappingSpecCommand(tenant_id="tenant_alpha", mapping_spec_id="non_existent")
    )

    assert res.is_err
    assert res.unwrap_err().code == IpErrorCode.MAPPING_SPEC_NOT_FOUND


@pytest.mark.asyncio
async def test_delete_mapping_spec_rejected_when_referenced_by_active_stitch() -> None:
    uow = _StubControlPlaneUoW()
    spec = MappingSpec(
        id="fmap_test_locked",
        tenant_id="tenant_alpha",
        name="In Use Spec",
        source_type="canonical.event",
        target_connection_id="conn_target",
        target_entity_name="target_queue",
    )
    await uow.mapping_specs.save(spec)

    stitch = Stitch(
        id="stch_active_user",
        tenant_id="tenant_alpha",
        workflow_id="wf_pipe",
        workflow_version=1,
        canonical_event_type="canonical.event",
        mapping_spec_id="fmap_test_locked",
        is_active=True,
    )
    await uow.stitches.save(stitch)

    use_case = DeleteMappingSpecUseCase(uow=uow)
    res = await use_case.execute(
        DeleteMappingSpecCommand(tenant_id="tenant_alpha", mapping_spec_id="fmap_test_locked")
    )

    assert res.is_err
    err = res.unwrap_err()
    assert err.code == IpErrorCode.MAPPING_SPEC_IN_USE
    assert "stch_active_user" in err.message
    # Verify not deleted
    assert (
        await uow.mapping_specs.get_by_id(
            tenant_id="tenant_alpha", mapping_spec_id="fmap_test_locked"
        )
        is not None
    )
