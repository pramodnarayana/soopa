from __future__ import annotations

from typing import cast

import pytest
from database.outbox_serializer import deserialize_event_envelope_json
from database.replication_watermark import parse_postgres_lsn
from outbox.adapters.outbound.sqlalchemy_logical_outbox_emitter import (
    SqlAlchemyLogicalOutboxEmitter,
)
from outbox.domain.constants import LogicalOutboxChannel
from outbox.testing.fakes import FakeTransactionalStreamEmitter
from seedwork.events import EventEnvelope, EventProcessingLane
from sqlalchemy.ext.asyncio import AsyncSession


class _ScalarResult:
    def __init__(self, value: str) -> None:
        self._value = value

    def scalar_one(self) -> str:
        return self._value


class _FakeLogicalSession:
    def __init__(self, lsn_sequence: list[str]) -> None:
        self._lsns = list(lsn_sequence)
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def execute(self, stmt: object, params: dict[str, str]) -> _ScalarResult:
        self.calls.append((str(stmt), params))
        return _ScalarResult(self._lsns.pop(0))


def _make_envelope(idx: int) -> EventEnvelope:
    return EventEnvelope(
        id=f"evt_000{idx}",
        source="soopa.orders",
        event_type="order.placed",
        tenant_id="iam_ten_alpha01",
        idempotency_key=f"idem_000{idx}",
        payload={"order_total_cents": 19900 * idx},
        trace_id="trc_01",
        correlation_id="cor_01",
        lane=EventProcessingLane.REALTIME,
    )


@pytest.mark.asyncio
async def test_sqlalchemy_logical_outbox_emitter_emits_transactional_messages() -> None:
    raw_session = _FakeLogicalSession(["0/16B3748", "0/16B3890"])
    emitter = SqlAlchemyLogicalOutboxEmitter(
        session=cast(AsyncSession, raw_session),
        channel=LogicalOutboxChannel.SOOPA_OUTBOX,
    )

    e1 = _make_envelope(1)
    e2 = _make_envelope(2)
    result = await emitter.emit_transactional_batch([e1, e2])

    assert result.emitted_count == 2
    assert result.high_watermark == parse_postgres_lsn("0/16B3890")
    assert len(raw_session.calls) == 2
    assert "pg_logical_emit_message(true" in raw_session.calls[0][0]
    assert raw_session.calls[0][1]["prefix"] == "soopa.outbox"

    rehydrated = deserialize_event_envelope_json(raw_session.calls[0][1]["content"])
    assert rehydrated == e1


@pytest.mark.asyncio
async def test_sqlalchemy_logical_outbox_emitter_handles_empty_batch() -> None:
    raw_session = _FakeLogicalSession([])
    emitter = SqlAlchemyLogicalOutboxEmitter(session=cast(AsyncSession, raw_session))
    result = await emitter.emit_transactional_batch([])
    assert result.emitted_count == 0
    assert result.high_watermark is None
    assert raw_session.calls == []


@pytest.mark.asyncio
async def test_fake_transactional_stream_emitter_tracks_watermarks() -> None:
    fake = FakeTransactionalStreamEmitter()
    res = await fake.emit_transactional_batch([_make_envelope(1), _make_envelope(2)])
    assert res.emitted_count == 2
    assert res.high_watermark is not None
    assert len(fake.emitted_envelopes) == 2
