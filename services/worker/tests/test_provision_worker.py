from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from worker.provision.main import poll_global_outbox, replicate_tenant_config

pytestmark = pytest.mark.asyncio


@patch("worker.provision.main.replicate_tenant_config")
async def test_poll_global_outbox_processes_event(mock_replicate: AsyncMock) -> None:
    mock_db_router = MagicMock()
    mock_resolver = MagicMock()

    mock_resolver.resolve = AsyncMock(return_value=("shard1", "url"))

    mock_global_gen = AsyncMock()
    mock_global_session = AsyncMock()
    mock_db_router.get_global_session.return_value = mock_global_gen
    mock_global_gen.__anext__.return_value = mock_global_session

    mock_tenant_gen = AsyncMock()
    mock_tenant_session = AsyncMock()
    mock_db_router.get_tenant_session.return_value = mock_tenant_gen
    mock_tenant_gen.__anext__.return_value = mock_tenant_session

    mock_outbox_event = MagicMock()
    mock_outbox_event.payload = {"tenant_id": 99}

    mock_result = MagicMock()
    # Return event first time, then raise exception to break loop
    mock_result.scalar_one_or_none.return_value = mock_outbox_event

    import asyncio

    mock_global_session.execute.side_effect = [mock_result, asyncio.CancelledError()]

    with pytest.raises(asyncio.CancelledError):
        await poll_global_outbox(mock_db_router, mock_resolver)

    mock_replicate.assert_awaited_once_with(99, mock_global_session, mock_tenant_session)
    assert mock_outbox_event.status == "PROCESSED"
    mock_global_session.commit.assert_awaited_once()


async def test_replicate_tenant_config() -> None:
    mock_global_session = AsyncMock()
    mock_tenant_session = AsyncMock()

    # Mock global execution to return some scalars for TP, Conn, Route
    mock_tp = MagicMock()
    mock_tp.id = "tp-uuid"
    mock_tp.partner_name = "Acme Corp"
    mock_tp.as2_id = "ACME"
    mock_tp.direction = "BOTH"
    mock_tp.active = True

    mock_conn = MagicMock()
    mock_conn.id = "conn-uuid"
    mock_conn.trading_partner_id = "tp-uuid"
    mock_conn.connection_type = "AS2"
    mock_conn.host = "as2.acme.com"
    mock_conn.port = 4080
    mock_conn.direction = "INBOUND"
    mock_conn.credentials_vault_ref = "vault://acme"
    mock_conn.poll_interval_secs = None
    mock_conn.active = True

    mock_route = MagicMock()
    mock_route.id = "route-uuid"
    mock_route.source_partner_id = "tp-uuid"
    mock_route.target_partner_id = "tp-uuid-2"
    mock_route.source_format = "X12"
    mock_route.target_format = "JSON"
    mock_route.transaction_type = "850"
    mock_route.active = True

    # We have 3 queries in replicate_tenant_config (TP, Conn, Route)
    mock_result_tp = MagicMock()
    mock_result_tp.scalars.return_value = [mock_tp]

    mock_result_conn = MagicMock()
    mock_result_conn.scalars.return_value = [mock_conn]

    mock_result_route = MagicMock()
    mock_result_route.scalars.return_value = [mock_route]

    mock_global_session.execute.side_effect = [mock_result_tp, mock_result_conn, mock_result_route]

    await replicate_tenant_config(99, mock_global_session, mock_tenant_session)

    assert mock_global_session.execute.await_count == 3
    mock_tenant_session.commit.assert_awaited_once()
