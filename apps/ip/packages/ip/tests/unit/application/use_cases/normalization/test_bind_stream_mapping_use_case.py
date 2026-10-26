"""Unit tests for BindStreamMappingUseCase using in-memory test fakes."""

from __future__ import annotations

import pytest
from ip.engine.application.use_cases.normalization.bind_stream_mapping_use_case import (
    BindStreamMappingCommand,
    BindStreamMappingUseCase,
)
from ip.engine.domain.enums import MappingMode
from ip.engine.domain.events import MappingBindingChangedEvent
from ip.engine.domain.normalization import MappingBinding
from ip.engine.domain.services.mapper_registry import InMemoryMapperRegistry
from ip.engine.ports.outbound.catalog_repository_port import CatalogRepositoryPort
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.mapping_binding_repository_port import (
    MappingBindingRepositoryPort,
)
from ip.engine.ports.outbound.stream_state_repository_port import (
    StreamStateRepositoryPort,
)
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort
from seedwork.events import DomainEvent


class FakeMappingBindingRepository(MappingBindingRepositoryPort):
    def __init__(self) -> None:
        self.bindings: dict[tuple[str, str, str], MappingBinding] = {}
        self.events: list[DomainEvent] = []

    async def get_by_stream(
        self, *, tenant_id: str, connection_id: str, stream: str
    ) -> MappingBinding | None:
        return self.bindings.get((tenant_id, connection_id, stream))

    async def save(self, binding: MappingBinding) -> None:
        self.bindings[(binding.tenant_id, binding.connection_id, binding.stream)] = binding
        self.events.extend(binding.domain_events)
        binding.clear_domain_events()

    async def list_by_connection(
        self, *, tenant_id: str, connection_id: str
    ) -> list[MappingBinding]:
        return [
            b
            for b in self.bindings.values()
            if b.tenant_id == tenant_id and b.connection_id == connection_id
        ]


class FakeControlPlaneUoW(IpControlPlaneUnitOfWorkPort):
    connections: ConnectionRepositoryPort
    catalogs: CatalogRepositoryPort
    stream_states: StreamStateRepositoryPort
    sync_runs: SyncRunRepositoryPort
    mapping_bindings: FakeMappingBindingRepository

    def __init__(self) -> None:
        self.mapping_bindings = FakeMappingBindingRepository()
        self.committed = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass

    async def __aenter__(self) -> FakeControlPlaneUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


@pytest.mark.asyncio
async def test_bind_new_stream_mapping() -> None:
    uow = FakeControlPlaneUoW()
    use_case = BindStreamMappingUseCase(uow)

    command = BindStreamMappingCommand(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
        mode=MappingMode.ACTIVE,
        shadow_mapping_version=2,
    )

    result = await use_case.execute(command)
    assert result.is_ok
    dto = result.unwrap()
    assert dto.binding_id.startswith("ip_bind_")
    assert dto.connection_id == "conn_1"
    assert dto.stream == "readings"
    assert dto.mapping_id == "energy.ami_meter_reading"
    assert dto.mapping_version == 1
    assert dto.shadow_mapping_version == 2
    assert dto.mode == "ACTIVE"
    assert uow.committed

    # Verify event emitted
    assert len(uow.mapping_bindings.events) == 1
    event = uow.mapping_bindings.events[0]
    assert isinstance(event, MappingBindingChangedEvent)
    assert event.mapping_id == "energy.ami_meter_reading"
    assert event.mapping_version == 1


@pytest.mark.asyncio
async def test_update_existing_stream_mapping() -> None:
    uow = FakeControlPlaneUoW()
    existing = MappingBinding.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
    )
    await uow.mapping_bindings.save(existing)

    use_case = BindStreamMappingUseCase(uow)
    command = BindStreamMappingCommand(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        mapping_id="energy.ami_meter_reading",
        mapping_version=2,
        mode=MappingMode.SHADOW,
    )

    result = await use_case.execute(command)
    assert result.is_ok
    dto = result.unwrap()
    assert dto.binding_id == existing.id
    assert dto.mapping_version == 2
    assert dto.mode == "SHADOW"


@pytest.mark.asyncio
async def test_bind_stream_mapping_rejects_unregistered_version() -> None:
    uow = FakeControlPlaneUoW()
    registry = InMemoryMapperRegistry()
    use_case = BindStreamMappingUseCase(uow, mapper_registry=registry)

    command = BindStreamMappingCommand(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        mapping_id="energy.unregistered_mapper",
        mapping_version=1,
    )
    result = await use_case.execute(command)
    assert result.is_err
    assert "not registered" in result.unwrap_err().message
