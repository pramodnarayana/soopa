"""Unit tests for InMemoryTransformerRegistry."""

from dataclasses import dataclass

from ip.engine.domain.normalization import (
    ReplicaSnapshot,
    TransformationContext,
    TransformationResult,
)
from ip.engine.domain.services.transformer_registry import InMemoryTransformerRegistry


@dataclass(frozen=True)
class DummyTransformer:
    xfrm_id: str
    xfrm_ver: int
    targets: tuple[str, ...] = ("energy.meter_reading",)

    @property
    def transformation_id(self) -> str:
        return self.xfrm_id

    @property
    def transformation_version(self) -> int:
        return self.xfrm_ver

    @property
    def target_types(self) -> tuple[str, ...]:
        return self.targets

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult:
        return TransformationResult()


def test_transformer_registry_register_and_get() -> None:
    registry = InMemoryTransformerRegistry()
    m1 = DummyTransformer("energy.ami", 1)
    m2 = DummyTransformer("energy.ami", 2)
    m_other = DummyTransformer("tms.loads", 1)

    registry.register(m1)
    registry.register(m2)
    registry.register(m_other)

    assert registry.get("energy.ami", 1) == m1
    assert registry.get("energy.ami", 2) == m2
    assert registry.get("energy.ami", 3) is None
    assert registry.get("nonexistent", 1) is None


def test_transformer_registry_get_latest() -> None:
    registry = InMemoryTransformerRegistry()
    m1 = DummyTransformer("energy.ami", 1)
    m2 = DummyTransformer("energy.ami", 2)
    m3 = DummyTransformer("energy.ami", 3)

    registry.register(m1)
    registry.register(m3)
    registry.register(m2)

    latest = registry.get_latest("energy.ami")
    assert latest is not None
    assert latest.transformation_version == 3

    assert registry.get_latest("unknown") is None


def test_transformer_registry_list_transformers() -> None:
    registry = InMemoryTransformerRegistry()
    m1 = DummyTransformer("energy.ami", 1)
    m2 = DummyTransformer("tms.loads", 1)

    registry.register(m1)
    registry.register(m2)

    all_transformers = registry.list_transformers()
    assert len(all_transformers) == 2
    assert m1 in all_transformers
    assert m2 in all_transformers
