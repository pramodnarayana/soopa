from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from database.events import EventEnvelope
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox, EdiJson
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from outbox.domain.constants import OutboxStatus
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from sqlalchemy import and_, func, select, update


class MockOutboxRepository(OutboxRepositoryPort):
    def __init__(self, session_factory: Any):
        self.session_factory = session_factory

    async def sweep_stuck_events(self, lock_lease_ms: int) -> int:
        async with self.session_factory() as session:
            stmt = (
                update(DataPlaneOutbox)
                .where(
                    and_(
                        DataPlaneOutbox.status == OutboxStatus.PROCESSING.value,
                        DataPlaneOutbox.lease_expires_at < func.now(),
                    )
                )
                .values(status=OutboxStatus.PENDING.value, lease_expires_at=None)
            )
            res = await session.execute(stmt)
            await session.commit()
            return int(getattr(res, "rowcount", 0))

    async def claim_next_events(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[EventEnvelope]:
        async with self.session_factory() as session:
            subq = (
                select(DataPlaneOutbox.id)
                .where(DataPlaneOutbox.status == OutboxStatus.PENDING.value)
                .order_by(DataPlaneOutbox.created_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
                .scalar_subquery()
            )

            stmt = (
                update(DataPlaneOutbox)
                .where(DataPlaneOutbox.id.in_(subq))
                .values(
                    status=OutboxStatus.PROCESSING.value,
                    updated_at=func.now(),
                    owner_token=worker_id,
                )
                .returning(DataPlaneOutbox)
            )

            result = await session.execute(stmt)
            await session.commit()

            return [
                EventEnvelope(
                    id=str(row.id),
                    tenant_id=str(row.tenant_id) if row.tenant_id else None,
                    event_type=str(row.event_type),
                    payload=row.payload,
                    idempotency_key=row.idempotency_key,
                    source="edi_data_plane",
                )
                for row in result.scalars()
            ]

    async def mark_completed(self, event_id: str, worker_id: str) -> None:
        async with self.session_factory() as session:
            stmt = (
                update(DataPlaneOutbox)
                .where(
                    and_(
                        DataPlaneOutbox.id == event_id,
                        DataPlaneOutbox.status == OutboxStatus.PROCESSING.value,
                        DataPlaneOutbox.owner_token == worker_id,
                    )
                )
                .values(
                    status=OutboxStatus.PROCESSED.value,
                    lease_expires_at=None,
                    owner_token=None,
                    updated_at=func.now(),
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def mark_failed(self, event_id: str, worker_id: str, error_message: str) -> None:
        pass


@pytest.mark.asyncio
async def test_e2e_unified_api_to_outbox_sweeper(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, Any],
    db_session_factory: Any,
) -> None:
    """
    E2E flow:
    1. HTTP POST to /api/v1/edi_json
    2. Assert EdiJson and DataPlaneOutbox (PENDING) records exist.
    3. Run OutboxSweeperUseCase.
    4. Assert DataPlaneOutbox is COMPLETED and mock publisher was called.
    """
    tenant_id = seeded_api_token["tenant_id"]

    # 1. HTTP Ingress (Unified API)
    payload = {
        "trading_partner_id": "tp_123",
        "transaction_type": "850",
        "payload": {"key": "value"},
    }

    response = await auth_client.post("/api/v1/edi_json", json=payload)

    assert response.status_code == 202, response.text
    response_data = response.json()
    assert "trace_id" in response_data
    trace_id = response_data["trace_id"]

    # 2. Persistence Assertion (Read directly from database)
    async with db_session_factory() as session:
        # Check EdiJson record
        edi_json_result = await session.execute(select(EdiJson).where(EdiJson.trace_id == trace_id))
        edi_json_record = edi_json_result.scalar_one_or_none()
        assert edi_json_record is not None
        assert edi_json_record.tenant_id == tenant_id
        assert edi_json_record.transaction_type == "850"

        # Check Outbox Event
        outbox_result = await session.execute(
            select(DataPlaneOutbox).where(DataPlaneOutbox.tenant_id == tenant_id)
        )
        outbox_events = outbox_result.scalars().all()
        assert len(outbox_events) == 1

        outbox_event = outbox_events[0]
        assert outbox_event.status == OutboxStatus.PENDING.value
        event_payload = outbox_event.payload
        assert event_payload["trace_id"] == trace_id

    # 3. Worker Processing (EDI Background Worker simulation)
    mock_publisher = AsyncMock()
    mock_publisher.publish_batch = AsyncMock(side_effect=lambda events: [e.id for e in events])

    outbox_repo = MockOutboxRepository(session_factory=db_session_factory)
    sweeper_use_case = OutboxSweeperUseCase(repository=outbox_repo, publisher=mock_publisher)

    # Act: Sweep the outbox
    await sweeper_use_case.execute()

    # 4. Final State Verification
    async with db_session_factory() as session:
        outbox_result = await session.execute(
            select(DataPlaneOutbox).where(DataPlaneOutbox.id == outbox_event.id)
        )
        updated_event = outbox_result.scalar_one_or_none()

        assert updated_event is not None
        assert updated_event.status == OutboxStatus.PROCESSED.value

    mock_publisher.publish_batch.assert_called_once()
