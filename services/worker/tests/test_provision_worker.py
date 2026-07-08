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


def _make_scalars_result(items: list) -> MagicMock:
    """Creates a mock SQLAlchemy result that supports both iteration and .scalars().all()."""
    mock_result = MagicMock()
    # Support for `for item in result.scalars():` (iteration)
    mock_result.scalars.return_value = iter(items)
    # Support for `result.scalars().all()` (in sync_deletes)
    mock_scalars = MagicMock()
    mock_scalars.__iter__ = MagicMock(return_value=iter(items))
    mock_scalars.all.return_value = items
    mock_result.scalars.return_value = mock_scalars
    return mock_result


def _make_empty_scalars_result() -> MagicMock:
    """Creates a mock that returns empty for both iteration and .scalars().all()."""
    return _make_scalars_result([])


async def test_replicate_tenant_config() -> None:
    mock_global_session = AsyncMock()
    mock_tenant_session = AsyncMock()

    # Mock global execution to return some scalars for AS2Partner
    mock_tp = MagicMock()
    mock_tp.id = "tp-uuid"
    mock_tp.tenant_id = 99
    mock_tp.name = "Acme Corp AS2"
    mock_tp.as2_id = "ACME"
    mock_tp.is_local = False
    mock_tp.public_cert_pem = "PEM"
    mock_tp.public_cert_vault_ref = "vault://acme-pub"
    mock_tp.private_key_vault_ref = None
    mock_tp.prev_public_cert_pem = None
    mock_tp.prev_public_cert_vault_ref = None
    mock_tp.prev_private_key_vault_ref = None
    mock_tp.url = None
    mock_tp.active = True

    mock_ps = MagicMock()
    mock_ps.id = "ps-uuid"
    mock_ps.tenant_id = 99
    mock_ps.name = "Partnership 1"
    mock_ps.local_partner_id = "loc"
    mock_ps.remote_partner_id = "rem"
    mock_ps.credentials_vault_ref = "ref"
    mock_ps.mdn_type = "SYNC"
    mock_ps.mdn_url = None
    mock_ps.encryption_algorithm = "AES"
    mock_ps.signature_algorithm = "SHA"
    mock_ps.advanced_flags = None

    mock_ps.active = True

    # replicate_tenant_config makes 6 global_session.execute calls for replication:
    #   1. AS2Partners, 2. AS2Partnerships, 3. SFTPPartners,
    #   4. Webhooks, 5. InboundRoutes, 6. OutboundRoutes
    # Then sync_deletes is called 6 times, each making 1 global_session.execute call
    #   (the second execute per sync_deletes goes to tenant_session).
    # Total global_session.execute calls = 6 (replicate) + 6 (sync_deletes global IDs) = 12

    mock_global_session.execute.side_effect = [
        # Replication phase (6 calls)
        _make_scalars_result([mock_tp]),  # AS2Partners
        _make_scalars_result([mock_ps]),  # AS2Partnerships
        _make_empty_scalars_result(),  # SFTPPartners
        _make_empty_scalars_result(),  # Webhooks
        _make_empty_scalars_result(),  # InboundRoutes
        _make_empty_scalars_result(),  # OutboundRoutes
        # sync_deletes phase - global IDs queries (6 calls)
        _make_empty_scalars_result(),  # AS2Partners global IDs
        _make_empty_scalars_result(),  # AS2Partnerships global IDs
        _make_empty_scalars_result(),  # SFTPPartners global IDs
        _make_empty_scalars_result(),  # Webhooks global IDs
        _make_empty_scalars_result(),  # InboundRoutes global IDs
        _make_empty_scalars_result(),  # OutboundRoutes global IDs
    ]

    # sync_deletes also queries tenant_session for IDs (6 calls)
    mock_tenant_session.execute.return_value = _make_empty_scalars_result()

    await replicate_tenant_config(99, mock_global_session, mock_tenant_session)

    assert mock_global_session.execute.await_count == 12
    mock_tenant_session.commit.assert_awaited_once()
