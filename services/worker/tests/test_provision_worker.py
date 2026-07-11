from unittest.mock import AsyncMock, MagicMock

import pytest
from worker.core.service import ProvisioningWorkerService

pytestmark = pytest.mark.asyncio


async def test_process_next_event_no_event() -> None:
    mock_tenant = AsyncMock()
    mock_outbox = MagicMock()
    mock_replication = AsyncMock()

    # Setup the async context manager to yield None
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_cm():
        yield None

    mock_outbox.process_next_event.return_value = fake_cm()

    svc = ProvisioningWorkerService(mock_tenant, mock_outbox, mock_replication)
    result = await svc.process_next_event()
    assert result is False
    mock_replication.replicate_tenant_configuration.assert_not_called()


async def test_process_next_event_tenant_specific() -> None:
    mock_tenant = AsyncMock()
    mock_outbox = MagicMock()
    mock_replication = AsyncMock()

    mock_event = MagicMock()
    mock_event.payload = {"tenant_id": 99}

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_cm():
        yield mock_event

    mock_outbox.process_next_event.return_value = fake_cm()

    svc = ProvisioningWorkerService(mock_tenant, mock_outbox, mock_replication)
    result = await svc.process_next_event()
    assert result is True
    mock_replication.replicate_tenant_configuration.assert_awaited_once_with(99)


async def test_process_next_event_global() -> None:
    mock_tenant = AsyncMock()
    mock_outbox = MagicMock()
    mock_replication = AsyncMock()

    mock_event = MagicMock()
    mock_event.payload = {"tenant_id": 0}

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_cm():
        yield mock_event

    mock_outbox.process_next_event.return_value = fake_cm()

    mock_tenant.get_all_tenant_ids.return_value = [1, 2, 3]

    svc = ProvisioningWorkerService(mock_tenant, mock_outbox, mock_replication)
    result = await svc.process_next_event()

    assert result is True
    assert mock_replication.replicate_tenant_configuration.call_count == 3
