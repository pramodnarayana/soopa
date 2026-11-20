"""Unit tests for declarative MappingSpec domain aggregate and control plane use cases."""

from __future__ import annotations

from collections.abc import Sequence
from types import TracebackType

import pytest
from ip.engine.application.use_cases.mapping.mapping_spec_use_cases import (
    GetMappingSpecQuery,
    GetMappingSpecUseCase,
    ListMappingSpecsQuery,
    ListMappingSpecsUseCase,
    MappingRuleDTO,
    SaveMappingSpecCommand,
    SaveMappingSpecUseCase,
)
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.connection.enums import AuthType, ConnectionStatus
from ip.engine.domain.enums import IpEventType
from ip.engine.domain.exceptions import DuplicateConnectionFingerprintError, Result
from ip.engine.domain.mapping import MappingRule, MappingRuleType, MappingSpec
from ip.engine.domain.mapping.events import MappingSpecSavedEvent
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


class _InMemoryConnectionRepo(ConnectionRepositoryPort):
    def __init__(self) -> None:
        self.items: dict[str, Connection] = {}

    def add_stub(self, connection_id: str, tenant_id: str) -> Connection:
        conn = Connection(
            id=connection_id,
            tenant_id=tenant_id,
            app_id="kafka",
            name=f"Conn {connection_id}",
            auth_type=AuthType.NO_AUTH,
            connection_fingerprint=f"fp_{connection_id}",
            status=ConnectionStatus.ACTIVE,
        )
        self.items[connection_id] = conn
        return conn

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


class _InMemoryMappingSpecRepository(MappingSpecRepositoryPort):
    def __init__(self) -> None:
        self.specs: dict[str, MappingSpec] = {}

    async def save(self, spec: MappingSpec) -> None:
        self.specs[spec.id] = spec

    async def get_by_id(
        self,
        *,
        tenant_id: str,
        mapping_spec_id: str,
    ) -> MappingSpec | None:
        spec = self.specs.get(mapping_spec_id)
        if spec is not None and spec.tenant_id == tenant_id:
            return spec
        return None

    async def get_latest_by_target(
        self,
        *,
        tenant_id: str,
        target_connection_id: str,
        target_entity_name: str,
    ) -> MappingSpec | None:
        matching = [
            s
            for s in self.specs.values()
            if s.tenant_id == tenant_id
            and s.target_connection_id == target_connection_id
            and s.target_entity_name == target_entity_name
        ]
        if not matching:
            return None
        return max(matching, key=lambda s: s.version)

    async def list_by_tenant(
        self,
        *,
        tenant_id: str,
        source_type: str | None = None,
        target_connection_id: str | None = None,
    ) -> list[MappingSpec]:
        return [
            spec
            for spec in self.specs.values()
            if spec.tenant_id == tenant_id
            and (source_type is None or spec.source_type == source_type)
            and (target_connection_id is None or spec.target_connection_id == target_connection_id)
        ]


class _StubControlPlaneUoW(IpControlPlaneUnitOfWorkPort):
    connections: _InMemoryConnectionRepo
    mapping_specs: _InMemoryMappingSpecRepository

    def __init__(self) -> None:
        self.connections = _InMemoryConnectionRepo()
        self.mapping_specs = _InMemoryMappingSpecRepository()
        self.committed = False
        self.rolled_back = False

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
    def stitches(self) -> StitchRepositoryPort:
        raise NotImplementedError

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def __aenter__(self) -> _StubControlPlaneUoW:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()


def test_mapping_spec_domain_creation_emits_saved_event() -> None:
    rules = (
        MappingRule(
            target_field="device_identifier",
            rule_type=MappingRuleType.DIRECT,
            source_field="device_id",
        ),
        MappingRule(
            target_field="protocol_version",
            rule_type=MappingRuleType.CONSTANT,
            constant_value="2.0",
        ),
        MappingRule(
            target_field="reading_scaled",
            rule_type=MappingRuleType.EXPRESSION,
            expression="reading_raw",
        ),
        MappingRule(
            target_field="internal_notes",
            rule_type=MappingRuleType.IGNORE,
        ),
    )

    spec = MappingSpec(
        id="ip_fmap_12345678",
        tenant_id="tenant_gamma",
        name="Device Telemetry Translation",
        description="Maps canonical device reading to destination schema",
        source_type="canonical.device_reading.v1",
        target_connection_id="conn_dest_kafka",
        target_entity_name="devices.telemetry.inbound",
        rules=rules,
        version=1,
    )
    spec.record_saved()

    assert spec.id.startswith("ip_fmap_")
    assert spec.tenant_id == "tenant_gamma"
    assert spec.name == "Device Telemetry Translation"
    assert len(spec.rules) == 4
    assert spec.version == 1

    events = spec.pull_domain_events()
    assert len(events) == 1
    event = events[0]
    assert event.event_name == IpEventType.MAPPING_SPEC_SAVED
    assert isinstance(event, MappingSpecSavedEvent)
    assert event.mapping_spec_id == spec.id


def test_mapping_spec_projection_transforms_payload() -> None:
    rules = (
        MappingRule(
            target_field="destination_device_id",
            rule_type=MappingRuleType.DIRECT,
            source_field="device_id",
        ),
        MappingRule(
            target_field="system_source",
            rule_type=MappingRuleType.CONSTANT,
            constant_value="IP_PLATFORM",
        ),
        MappingRule(
            target_field="ignored_field",
            rule_type=MappingRuleType.IGNORE,
        ),
    )

    spec = MappingSpec(
        id="ip_fmap_12345678",
        tenant_id="tenant_gamma",
        name="Device Telemetry Translation",
        description="Maps canonical device reading to destination schema",
        source_type="canonical.device_reading.v1",
        target_connection_id="conn_dest_kafka",
        target_entity_name="devices.telemetry.inbound",
        rules=rules,
        version=1,
    )

    source_payload = {
        "device_id": "DEV-9942",
        "raw_reading": 42.5,
        "internal_metadata": "confidential",
    }

    projected = spec.project(source_payload)

    assert projected == {
        "destination_device_id": "DEV-9942",
        "system_source": "IP_PLATFORM",
    }
    assert "ignored_field" not in projected
    assert "internal_metadata" not in projected


@pytest.mark.asyncio
async def test_save_mapping_spec_use_case_persists_new_spec() -> None:
    uow = _StubControlPlaneUoW()
    uow.connections.add_stub("conn_kafka_out", "tenant_alpha")
    use_case = SaveMappingSpecUseCase(uow=uow)

    cmd = SaveMappingSpecCommand(
        tenant_id="tenant_alpha",
        name="Sensor Data Mapper",
        description="Projects sensor data to destination topic",
        source_type="canonical.sensor_reading.v1",
        target_connection_id="conn_kafka_out",
        target_entity_name="sensor.readings.wire",
        rules=(
            MappingRuleDTO(
                target_field="sensor_id",
                rule_type="DIRECT",
                source_field="sensor_identifier",
            ),
            MappingRuleDTO(
                target_field="schema_rev",
                rule_type="CONSTANT",
                constant_value="v1.0",
            ),
        ),
    )

    result = await use_case.execute(cmd)

    assert result.is_ok
    dto = result.value
    assert dto.id.startswith("ip_fmap_")
    assert dto.tenant_id == "tenant_alpha"
    assert dto.name == "Sensor Data Mapper"
    assert len(dto.rules) == 2
    assert uow.committed

    saved = await uow.mapping_specs.get_by_id(tenant_id="tenant_alpha", mapping_spec_id=dto.id)
    assert saved is not None
    assert saved.target_entity_name == "sensor.readings.wire"


@pytest.mark.asyncio
async def test_save_mapping_spec_updates_existing_spec() -> None:
    uow = _StubControlPlaneUoW()
    uow.connections.add_stub("conn_kafka_1", "tenant_beta")
    use_case = SaveMappingSpecUseCase(uow=uow)

    first_cmd = SaveMappingSpecCommand(
        tenant_id="tenant_beta",
        name="Initial Mapper",
        description="Initial version",
        source_type="canonical.reading.v1",
        target_connection_id="conn_kafka_1",
        target_entity_name="reading.topic",
        rules=(
            MappingRuleDTO(
                target_field="dest_val",
                rule_type="DIRECT",
                source_field="val",
            ),
        ),
    )
    first_res = await use_case.execute(first_cmd)
    assert first_res.is_ok
    spec_id = first_res.value.id

    update_cmd = SaveMappingSpecCommand(
        mapping_spec_id=spec_id,
        tenant_id="tenant_beta",
        name="Updated Mapper",
        description="Updated version with extra constant",
        source_type="canonical.reading.v1",
        target_connection_id="conn_kafka_1",
        target_entity_name="reading.topic",
        rules=(
            MappingRuleDTO(
                target_field="dest_val",
                rule_type="DIRECT",
                source_field="val",
            ),
            MappingRuleDTO(
                target_field="status_flag",
                rule_type="CONSTANT",
                constant_value="READY",
            ),
        ),
    )
    update_res = await use_case.execute(update_cmd)
    assert update_res.is_ok
    updated_dto = update_res.value
    assert updated_dto.id == spec_id
    assert updated_dto.name == "Updated Mapper"
    assert len(updated_dto.rules) == 2


@pytest.mark.asyncio
async def test_get_mapping_spec_returns_error_when_missing() -> None:
    uow = _StubControlPlaneUoW()
    use_case = GetMappingSpecUseCase(uow=uow)

    result = await use_case.execute(
        GetMappingSpecQuery(tenant_id="tenant_delta", mapping_spec_id="nonexistent_id")
    )
    assert result.is_err
    assert result.error.code.value == "MAPPING_SPEC_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_mapping_specs_filters_by_connection() -> None:
    uow = _StubControlPlaneUoW()
    uow.connections.add_stub("conn_kafka_a", "tenant_omega")
    uow.connections.add_stub("conn_kafka_b", "tenant_omega")
    save_uc = SaveMappingSpecUseCase(uow=uow)
    list_uc = ListMappingSpecsUseCase(uow=uow)

    await save_uc.execute(
        SaveMappingSpecCommand(
            tenant_id="tenant_omega",
            name="Spec A",
            description="",
            source_type="canonical.a.v1",
            target_connection_id="conn_kafka_a",
            target_entity_name="topic_a",
            rules=(),
        )
    )
    await save_uc.execute(
        SaveMappingSpecCommand(
            tenant_id="tenant_omega",
            name="Spec B",
            description="",
            source_type="canonical.b.v1",
            target_connection_id="conn_kafka_b",
            target_entity_name="topic_b",
            rules=(),
        )
    )

    all_specs = await list_uc.execute(ListMappingSpecsQuery(tenant_id="tenant_omega"))
    assert len(all_specs) == 2

    filtered = await list_uc.execute(
        ListMappingSpecsQuery(tenant_id="tenant_omega", target_connection_id="conn_kafka_a")
    )
    assert len(filtered) == 1
    assert filtered[0].target_connection_id == "conn_kafka_a"
