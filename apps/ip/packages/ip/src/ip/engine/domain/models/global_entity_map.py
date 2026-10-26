"""GlobalEntityMap (GEM) traced aggregate root for cross-system entity identity resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id
from strace.domain import TracedAggregateRoot


@dataclass(kw_only=True, eq=False)
class GlobalEntityMap(TracedAggregateRoot):
    """Traced Aggregate Root resolving Source System ID <-> Canonical ID <-> Destination System ID."""

    ID_PREFIX: ClassVar[str] = DomainIdPrefix.IP_GEM.value

    id: str
    entity_domain: str
    canonical_id: str
    source_connection_id: str
    source_entity_id: str
    dest_connection_id: str | None = None
    dest_entity_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        trace_id: str,
        entity_domain: str,
        canonical_id: str,
        source_connection_id: str,
        source_entity_id: str,
        dest_connection_id: str | None = None,
        dest_entity_id: str | None = None,
        correlation_id: str | None = None,
        parent_trace_id: str | None = None,
        original_trace_id: str | None = None,
        replay_count: int = 0,
    ) -> GlobalEntityMap:
        return cls(
            id=generate_id(cls.ID_PREFIX),
            tenant_id=tenant_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
            parent_trace_id=parent_trace_id,
            original_trace_id=original_trace_id,
            replay_count=replay_count,
            entity_domain=entity_domain,
            canonical_id=canonical_id,
            source_connection_id=source_connection_id,
            source_entity_id=source_entity_id,
            dest_connection_id=dest_connection_id,
            dest_entity_id=dest_entity_id,
            created_at=datetime.now(UTC),
        )

    def bind_destination(self, dest_connection_id: str, dest_entity_id: str) -> None:
        """Binds the destination connection and external ID once synced."""
        self.dest_connection_id = dest_connection_id
        self.dest_entity_id = dest_entity_id
