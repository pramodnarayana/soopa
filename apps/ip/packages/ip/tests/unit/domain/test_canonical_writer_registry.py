"""Unit tests for CanonicalWriterRegistry."""

from ip.engine.domain.normalization.registries import CanonicalWriterRegistry
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


def test_canonical_writer_registry_resolves_registered_writers() -> None:
    reg = CanonicalWriterRegistry()
    w1 = DummyWriter("canonical.record_alpha")
    w2 = DummyWriter("canonical.record_beta")

    reg.register(w1)
    reg.register(w2)

    assert reg.get("canonical.record_alpha") == w1
    assert reg.get("canonical.record_beta") == w2


def test_canonical_writer_registry_returns_none_for_unregistered_type() -> None:
    reg = CanonicalWriterRegistry()
    assert reg.get("canonical.unregistered") is None
