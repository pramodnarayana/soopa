from unittest.mock import AsyncMock, MagicMock

import pytest
from worker.core.errors import PermanentProvisioningError, TransientProvisioningError
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


async def test_process_next_event_missing_tenant_id() -> None:
    mock_tenant = AsyncMock()
    mock_outbox = MagicMock()
    mock_replication = AsyncMock()

    mock_event = MagicMock()
    mock_event.payload = {}

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_cm():
        yield mock_event

    mock_outbox.process_next_event.return_value = fake_cm()
    svc = ProvisioningWorkerService(mock_tenant, mock_outbox, mock_replication)

    with pytest.raises(PermanentProvisioningError):
        await svc.process_next_event()


async def test_process_next_event_permanent_error() -> None:
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
    mock_replication.replicate_tenant_configuration.side_effect = PermanentProvisioningError("test")

    svc = ProvisioningWorkerService(mock_tenant, mock_outbox, mock_replication)

    with pytest.raises(PermanentProvisioningError):
        await svc.process_next_event()


async def test_process_next_event_transient_error() -> None:
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
    mock_replication.replicate_tenant_configuration.side_effect = TransientProvisioningError("test")

    svc = ProvisioningWorkerService(mock_tenant, mock_outbox, mock_replication)

    with pytest.raises(TransientProvisioningError):
        await svc.process_next_event()


async def test_process_next_event_global_partial_failure() -> None:
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
    mock_tenant.get_all_tenant_ids.return_value = [1, 2]

    # make it fail for tenant 2
    async def mock_replicate(t_id):
        if t_id == 2:
            raise Exception("Failure for tenant 2")

    mock_replication.replicate_tenant_configuration.side_effect = mock_replicate

    svc = ProvisioningWorkerService(mock_tenant, mock_outbox, mock_replication)

    with pytest.raises(TransientProvisioningError) as exc_info:
        await svc.process_next_event()
    assert "Global broadcasting failed for some tenants" in str(exc_info.value)


async def test_process_next_event_global_exception() -> None:
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
    # make get_all_tenant_ids raise a generic exception
    mock_tenant.get_all_tenant_ids.side_effect = Exception("DB Connection Error")

    svc = ProvisioningWorkerService(mock_tenant, mock_outbox, mock_replication)

    with pytest.raises(TransientProvisioningError) as exc_info:
        await svc.process_next_event()
    assert "Global broadcasting failed: DB Connection Error" in str(exc_info.value)
