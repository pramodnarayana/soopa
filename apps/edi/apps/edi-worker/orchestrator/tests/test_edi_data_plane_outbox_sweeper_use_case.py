from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from database.models.data_plane import DataPlaneOutbox

from worker.application.edi_data_plane_outbox_sweeper_use_case import (
    EdiDataPlaneOutboxSweeperUseCase,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_db_router() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_publisher() -> MagicMock:
    pub = MagicMock()
    mock_connect_ctx = MagicMock()
    mock_connect_ctx.__aenter__.return_value = pub
    mock_connect_ctx.__aexit__ = AsyncMock()
    pub.connect.return_value = mock_connect_ctx
    return pub


async def test_sweeper_executes_sweep_shard_for_all_shards(
    mock_db_router: MagicMock, mock_publisher: MagicMock
) -> None:
    """Test that sweep triggers for each returned shard in the global database."""
    # Mock global session returning shards
    mock_global_session = AsyncMock()

    # Fake Shard Object
    class FakeShard:
        def __init__(self, name: str, dsn: str):
            self.name = name
            self.dsn = dsn

    mock_res = MagicMock()
    mock_res.scalars().all.return_value = [
        FakeShard("shard_1", "dsn1"),
        FakeShard("shard_2", "dsn2"),
    ]
    mock_global_session.execute.return_value = mock_res

    async def global_session_gen(*args, **kwargs) -> AsyncGenerator[AsyncMock, None]:
        yield mock_global_session

    mock_db_router.get_global_session.side_effect = global_session_gen

    use_case = EdiDataPlaneOutboxSweeperUseCase(
        db_router=mock_db_router, message_publisher=mock_publisher
    )

    # Mock the internal _sweep_shard to avoid hitting DB
    use_case._sweep_shard = AsyncMock(side_effect=[5, 10])  # type: ignore

    total = await use_case.execute()

    assert total == 15
    assert use_case._sweep_shard.call_count == 2
    use_case._sweep_shard.assert_any_call("shard_1", "dsn1")
    use_case._sweep_shard.assert_any_call("shard_2", "dsn2")


@patch("worker.application.edi_data_plane_outbox_sweeper_use_case.AsyncSession")
async def test_sweeper_shard_processing_with_events(
    mock_session_cls: MagicMock, mock_db_router: MagicMock, mock_publisher: MagicMock
) -> None:
    """Test that _sweep_shard fetches pending events and passes them to the processor."""
    mock_engine = MagicMock()
    mock_db_router.get_engine = AsyncMock(return_value=mock_engine)

    mock_session_ctx = MagicMock()
    mock_session = AsyncMock()
    mock_session_ctx.__aenter__.return_value = mock_session
    mock_session_cls.return_value = mock_session_ctx

    use_case = EdiDataPlaneOutboxSweeperUseCase(
        db_router=mock_db_router, message_publisher=mock_publisher
    )

    # Mock the processor
    use_case.processor.process_batch = AsyncMock(return_value=3)

    # Fake events
    fake_events = [
        DataPlaneOutbox(id=1, event_type="TRANSFORM_EVENT"),
        DataPlaneOutbox(id=2, event_type="DELIVER_EVENT"),
        DataPlaneOutbox(id=3, event_type="TRANSFORM_COMPLETED"),
    ]
    mock_res = MagicMock()
    mock_res.scalars().all.return_value = fake_events
    mock_session.execute.return_value = mock_res

    processed = await use_case._sweep_shard("shard_1", "dsn1")

    assert processed == 3
    mock_session.execute.assert_called_once()
    use_case.processor.process_batch.assert_called_once_with(fake_events)
    mock_session.commit.assert_called_once()


@patch("worker.application.edi_data_plane_outbox_sweeper_use_case.AsyncSession")
async def test_sweeper_shard_processing_no_events(
    mock_session_cls: MagicMock, mock_db_router: MagicMock, mock_publisher: MagicMock
) -> None:
    """Test that _sweep_shard early returns if no pending events."""
    mock_engine = MagicMock()
    mock_db_router.get_engine = AsyncMock(return_value=mock_engine)

    mock_session_ctx = MagicMock()
    mock_session = AsyncMock()
    mock_session_ctx.__aenter__.return_value = mock_session
    mock_session_cls.return_value = mock_session_ctx

    use_case = EdiDataPlaneOutboxSweeperUseCase(
        db_router=mock_db_router, message_publisher=mock_publisher
    )

    use_case.processor.process_batch = AsyncMock()

    # Fake empty events
    mock_res = MagicMock()
    mock_res.scalars().all.return_value = []
    mock_session.execute.return_value = mock_res

    processed = await use_case._sweep_shard("shard_1", "dsn1")

    assert processed == 0
    mock_session.execute.assert_called_once()
    use_case.processor.process_batch.assert_not_called()
    mock_session.commit.assert_not_called()
