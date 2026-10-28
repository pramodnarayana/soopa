"""Unit tests for CanonicalWriterRegistry, CanonicalEntityRegistry, and ErrorPolicy."""

from ip.engine.domain.normalization import CanonicalEntityDefinition
from ip.engine.domain.services.canonical_entity_registry import CanonicalEntityRegistry
from ip.engine.domain.services.canonical_writer_registry import (
    InMemoryCanonicalWriterRegistry,
)
from ip.engine.domain.services.default_normalization_error_policy import (
    DefaultNormalizationErrorPolicy,
)
from seedwork.domain.types import JsonDict
from sqlalchemy.ext.asyncio import AsyncSession


class DummyWriter:
    def __init__(self, c_type: str) -> None:
        self._type = c_type

    @property
    def canonical_type(self) -> str:
        return self._type

    async def upsert(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        fields: JsonDict,
        extensions: JsonDict,
        trace_id: str,
        transformation_id: str,
        transformation_version: int,
        replica_id: str,
        replica_version: int,
        correlation_id: str | None = None,
    ) -> None:
        pass

    async def soft_delete(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        trace_id: str,
        correlation_id: str | None = None,
    ) -> None:
        pass


def test_canonical_writer_registry() -> None:
    reg = InMemoryCanonicalWriterRegistry()
    w1 = DummyWriter("energy.meter_reading")
    w2 = DummyWriter("energy.service_point")

    reg.register(w1)
    reg.register(w2)

    assert reg.get("energy.meter_reading") == w1
    assert reg.get("energy.service_point") == w2
    assert reg.get("tms.loads") is None


def test_canonical_entity_registry() -> None:
    reg = CanonicalEntityRegistry()
    d1 = CanonicalEntityDefinition(canonical_type="energy.meter_reading", schema_version=1)
    reg.register(d1)

    assert reg.get("energy.meter_reading") == d1
    assert reg.get("unknown") is None


def test_default_normalization_error_policy() -> None:
    policy = DefaultNormalizationErrorPolicy()

    # Terminal data/mapper failures
    assert policy.is_terminal_failure(ValueError("Invalid int")) is True
    assert policy.is_terminal_failure(KeyError("missing_col")) is True
    assert policy.is_terminal_failure(TypeError("NoneType not subscriptable")) is True

    # Infrastructure / unexpected exceptions
    assert policy.is_terminal_failure(ConnectionError("DB connection refused")) is False
    assert policy.is_terminal_failure(TimeoutError("DB query timed out")) is False
    assert policy.is_terminal_failure(RuntimeError("Unexpected thread termination")) is False
