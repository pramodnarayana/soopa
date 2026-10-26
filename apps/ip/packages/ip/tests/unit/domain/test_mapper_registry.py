"""Unit tests for InMemoryMapperRegistry."""

from dataclasses import dataclass

from ip.engine.domain.normalization import (
    MappingContext,
    MappingResult,
    ReplicaSnapshot,
)
from ip.engine.domain.services.mapper_registry import InMemoryMapperRegistry


@dataclass(frozen=True)
class DummyMapper:
    map_id: str
    map_ver: int
    targets: tuple[str, ...] = ("energy.meter_reading",)

    @property
    def mapping_id(self) -> str:
        return self.map_id

    @property
    def mapping_version(self) -> int:
        return self.map_ver

    @property
    def target_types(self) -> tuple[str, ...]:
        return self.targets

    def map(self, replica: ReplicaSnapshot, context: MappingContext) -> MappingResult:
        return MappingResult()


def test_mapper_registry_register_and_get() -> None:
    registry = InMemoryMapperRegistry()
    m1 = DummyMapper("energy.ami", 1)
    m2 = DummyMapper("energy.ami", 2)
    m_other = DummyMapper("tms.loads", 1)

    registry.register(m1)
    registry.register(m2)
    registry.register(m_other)

    assert registry.get("energy.ami", 1) == m1
    assert registry.get("energy.ami", 2) == m2
    assert registry.get("energy.ami", 3) is None
    assert registry.get("nonexistent", 1) is None


def test_mapper_registry_get_latest() -> None:
    registry = InMemoryMapperRegistry()
    m1 = DummyMapper("energy.ami", 1)
    m2 = DummyMapper("energy.ami", 2)
    m3 = DummyMapper("energy.ami", 3)

    registry.register(m1)
    registry.register(m3)
    registry.register(m2)

    latest = registry.get_latest("energy.ami")
    assert latest is not None
    assert latest.mapping_version == 3

    assert registry.get_latest("unknown") is None


def test_mapper_registry_list_mappers() -> None:
    registry = InMemoryMapperRegistry()
    m1 = DummyMapper("energy.ami", 1)
    m2 = DummyMapper("tms.loads", 1)

    registry.register(m1)
    registry.register(m2)

    all_mappers = registry.list_mappers()
    assert len(all_mappers) == 2
    assert m1 in all_mappers
    assert m2 in all_mappers
