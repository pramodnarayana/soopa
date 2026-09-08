from typing import Any

import httpx
import pytest
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox, EdiJson
from outbox.domain.constants import OutboxStatus
from sqlalchemy import select


@pytest.mark.asyncio
async def test_e2e_unified_api_ingress_to_outbox(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, Any],
    db_session_factory: Any,
) -> None:
    """
    E2E flow:
    1. HTTP POST to /api/v1/edi_json
    2. Assert EdiJson and DataPlaneOutbox (PENDING) records exist.
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
        edi_json_result = await session.execute(select(EdiJson).where(EdiJson.trace_id == trace_id))
        edi_json_record = edi_json_result.scalar_one_or_none()
        assert edi_json_record is not None

        outbox_result = await session.execute(
            select(DataPlaneOutbox).where(DataPlaneOutbox.tenant_id == tenant_id)
        )
        outbox_events = outbox_result.scalars().all()
        assert len(outbox_events) == 1

        outbox_event = outbox_events[0]
        assert outbox_event.status == OutboxStatus.PENDING.value
