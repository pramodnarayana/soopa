"""Unit tests for BindStreamTransformationUseCase using in-memory test fakes."""

from __future__ import annotations

import pytest
from ip.engine.application.use_cases.normalization.bind_stream_transformation_use_case import (
    BindStreamTransformationCommand,
    BindStreamTransformationUseCase,
)
from ip.engine.domain.enums import TransformationMode
from ip.engine.domain.events import TransformationChangedEvent
from ip.engine.domain.normalization import Transformation
from ip.engine.domain.services.transformer_registry import InMemoryTransformerRegistry
from ip.engine.ports.outbound.catalog_repository_port import CatalogRepositoryPort
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.stitch_repository_port import StitchRepositoryPort
from ip.engine.ports.outbound.stream_state_repository_port import (
    StreamStateRepositoryPort,
)
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort
from ip.engine.ports.outbound.transformation_repository_port import (
    TransformationRepositoryPort,
)
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort
from seedwork.events import DomainEvent


class FakeTransformationRepository(TransformationRepositoryPort):
    def __init__(self) -> None:
        self.transformations: dict[tuple[str, str, str], Transformation] = {}
        self.events: list[DomainEvent] = []

    async def get_by_stream(
        self, *, tenant_id: str, connection_id: str, stream: str
    ) -> Transformation | None:
        return self.transformations.get((tenant_id, connection_id, stream))

    async def save(self, transformation: Transformation) -> None:
        self.transformations[
            (transformation.tenant_id, transformation.connection_id, transformation.stream)
        ] = transformation
        self.events.extend(transformation.domain_events)
        transformation.clear_domain_events()

    async def list_by_connection(
        self, *, tenant_id: str, connection_id: str
    ) -> list[Transformation]:
        return [
            b
            for b in self.transformations.values()
            if b.tenant_id == tenant_id and b.connection_id == connection_id
        ]


class FakeControlPlaneUoW(IpControlPlaneUnitOfWorkPort):
    connections: ConnectionRepositoryPort
    catalogs: CatalogRepositoryPort
    stream_states: StreamStateRepositoryPort
    sync_runs: SyncRunRepositoryPort
    transformations: FakeTransformationRepository
    stitches: StitchRepositoryPort

    def __init__(self) -> None:
        self.transformations = FakeTransformationRepository()
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
async def test_bind_new_stream_transformation() -> None:
    uow = FakeControlPlaneUoW()
    use_case = BindStreamTransformationUseCase(uow)

    command = BindStreamTransformationCommand(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        transformation_id="energy.ami_meter_reading",
        transformation_version=1,
        mode=TransformationMode.ACTIVE,
        shadow_transformation_version=2,
    )

    result = await use_case.execute(command)
    assert result.is_ok
    dto = result.unwrap()
    assert dto.id.startswith("ip_xfrm_")
    assert dto.connection_id == "conn_1"
    assert dto.stream == "readings"
    assert dto.transformation_id == "energy.ami_meter_reading"
    assert dto.transformation_version == 1
    assert dto.shadow_transformation_version == 2
    assert dto.mode == "ACTIVE"
    assert uow.committed

    # Verify event emitted
    assert len(uow.transformations.events) == 1
    event = uow.transformations.events[0]
    assert isinstance(event, TransformationChangedEvent)
    assert event.transformation_id == "energy.ami_meter_reading"
    assert event.transformation_version == 1


@pytest.mark.asyncio
async def test_update_existing_stream_transformation() -> None:
    uow = FakeControlPlaneUoW()
    existing = Transformation.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        transformation_id="energy.ami_meter_reading",
        transformation_version=1,
    )
    await uow.transformations.save(existing)

    use_case = BindStreamTransformationUseCase(uow)
    command = BindStreamTransformationCommand(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        transformation_id="energy.ami_meter_reading",
        transformation_version=2,
        mode=TransformationMode.SHADOW,
    )

    result = await use_case.execute(command)
    assert result.is_ok
    dto = result.unwrap()
    assert dto.id == existing.id
    assert dto.transformation_version == 2
    assert dto.mode == "SHADOW"


@pytest.mark.asyncio
async def test_bind_stream_transformation_rejects_unregistered_version() -> None:
    uow = FakeControlPlaneUoW()
    registry = InMemoryTransformerRegistry()
    use_case = BindStreamTransformationUseCase(uow, transformer_registry=registry)

    command = BindStreamTransformationCommand(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        transformation_id="energy.unregistered_transformer",
        transformation_version=1,
    )
    result = await use_case.execute(command)
    assert result.is_err
    assert "not registered" in result.unwrap_err().message
