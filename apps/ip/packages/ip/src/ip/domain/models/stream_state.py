"""ConnectionStreamState aggregate root for tracking incremental sync checkpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.models import AggregateRoot
from seedwork.utils import generate_id

from ip.domain.constants import IpDomainIdPrefix
from ip.domain.events import StreamStateCheckpointedEvent


@dataclass(kw_only=True, eq=False)
class ConnectionStreamState(AggregateRoot):
    """Aggregate Root tracking cursor position and record counters for an individual stream."""

    ID_PREFIX: ClassVar[str] = IpDomainIdPrefix.STREAM_STATE

    id: str
    tenant_id: str
    connection_id: str
    stream_name: str
    cursor_field: str | None = None
    cursor_value: str | None = None
    records_synced_count: int = 0
    last_synced_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        stream_name: str,
        cursor_field: str | None = None,
        initial_cursor: str | None = None,
    ) -> ConnectionStreamState:
        """Initializes a new stream state tracking aggregate."""
        state_id = generate_id(cls.ID_PREFIX)
        return cls(
            id=state_id,
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name=stream_name,
            cursor_field=cursor_field,
            cursor_value=initial_cursor,
            records_synced_count=0,
            last_synced_at=datetime.now(UTC),
        )

    def advance_checkpoint(
        self,
        new_cursor_value: str,
        records_in_batch: int = 1,
        synced_at: datetime | None = None,
    ) -> None:
        """Advances the stream cursor checkpoint and increments synced record count."""
        self.cursor_value = new_cursor_value
        self.records_synced_count += max(0, records_in_batch)
        self.last_synced_at = synced_at or datetime.now(UTC)

        self.add_domain_event(
            StreamStateCheckpointedEvent(
                state_id=self.id,
                tenant_id=self.tenant_id,
                connection_id=self.connection_id,
                stream_name=self.stream_name,
                cursor_value=new_cursor_value,
                records_synced_count=self.records_synced_count,
            )
        )

    def reset_checkpoint(self) -> None:
        """Resets stream checkpoint to force full historical re-sync."""
        self.cursor_value = None
        self.records_synced_count = 0
        self.last_synced_at = datetime.now(UTC)
