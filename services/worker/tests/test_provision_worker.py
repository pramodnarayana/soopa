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

    # Mock global execution to return some scalars for AS2Partner
    mock_tp = MagicMock()
    mock_tp.id = "tp-uuid"
    mock_tp.tenant_id = 99
    mock_tp.name = "Acme Corp AS2"
    mock_tp.as2_id = "ACME"
    mock_tp.host = "as2.acme.com"
    mock_tp.port = 4080
    mock_tp.public_cert_pem = "PEM"
    mock_tp.credentials_vault_ref = "vault://acme"
    mock_tp.active = True

    # We have 1 query in replicate_tenant_config (AS2Partner)
    mock_result_tp = MagicMock()
    mock_result_tp.scalars.return_value = [mock_tp]

    mock_global_session.execute.side_effect = [mock_result_tp]

    await replicate_tenant_config(99, mock_global_session, mock_tenant_session)

    assert mock_global_session.execute.await_count == 1
    mock_tenant_session.commit.assert_awaited_once()
