"""
SQLAlchemy Transactional Logical Outbox Stream Emitter.

Implements Tier-2 zero-tuple-bloat transactional event emission via PostgreSQL
`pg_logical_emit_message(true, :prefix, :content)`. Because `transactional = true`,
messages are 100% ACID-bound to the enclosing `UnitOfWork` commit/rollback while
generating 0 heap tuples, 0 B-Tree index writes, and 0 Autovacuum dead tuples.
"""

from __future__ import annotations

from collections.abc import Sequence

import structlog
from database.outbox_serializer import serialize_event_envelope_json
from database.replication_watermark import parse_postgres_lsn
from outbox.domain.constants import LogicalOutboxChannel
from outbox.domain.models import LogicalStreamEmissionResult
from outbox.ports.transactional_stream_emitter_port import TransactionalStreamEmitterPort
from seedwork.events import EventEnvelope
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class SqlAlchemyLogicalOutboxEmitter(TransactionalStreamEmitterPort):
    """Emits `EventEnvelope` batches directly into PostgreSQL transactional WAL stream."""

    def __init__(
        self,
        session: AsyncSession,
        channel: LogicalOutboxChannel = LogicalOutboxChannel.SOOPA_OUTBOX,
    ) -> None:
        self._session = session
        self._channel = channel

    async def emit_transactional_batch(
        self,
        envelopes: Sequence[EventEnvelope],
    ) -> LogicalStreamEmissionResult:
        if not envelopes:
            return LogicalStreamEmissionResult(emitted_count=0, high_watermark=None)

        stmt = text("SELECT pg_logical_emit_message(true, :prefix, :content)::text")
        highest_watermark: int | None = None

        for envelope in envelopes:
            serialized = serialize_event_envelope_json(envelope)
            res = await self._session.execute(
                stmt,
                {
                    "prefix": self._channel.value,
                    "content": serialized,
                },
            )
            lsn_str = str(res.scalar_one())
            watermark = int(parse_postgres_lsn(lsn_str))
            if highest_watermark is None or watermark > highest_watermark:
                highest_watermark = watermark

        count = len(envelopes)
        logger.info(
            "logical_outbox_batch_emitted",
            channel=self._channel.value,
            emitted_count=count,
            high_watermark=highest_watermark,
        )
        return LogicalStreamEmissionResult(
            emitted_count=count,
            high_watermark=highest_watermark,
        )


__all__ = ["SqlAlchemyLogicalOutboxEmitter"]
