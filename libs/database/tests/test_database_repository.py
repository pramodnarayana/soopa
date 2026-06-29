import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from database.models.control_plane import AS2Partner
from database.repository import (
    EdiMessageRepository,
    TradingPartnerRepository,
)

pytestmark = pytest.mark.asyncio


async def test_trading_partner_repository_find_by_as2_id() -> None:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_partner = AS2Partner(as2_id="TEST-ID", name="Test", tenant_id=1)
    mock_result.scalar_one_or_none.return_value = mock_partner
    session.execute.return_value = mock_result

    repo = TradingPartnerRepository(session)
    result = await repo.find_by_as2_id("TEST-ID")

    assert result == mock_partner
    session.execute.assert_called_once()


@patch("database.repository.get_tenant_id", return_value=123)
async def test_edi_message_repository_save_message(mock_get_tenant_id: Any) -> None:
    session = AsyncMock()
    session.add = MagicMock()
    repo = EdiMessageRepository(session)

    result = await repo.save_message(
        trace_id=uuid.uuid4(),
        direction="INBOUND",
        connection_type="AS2",
        s3_key="s3://bucket/test.bin",
        sender_id="SENDER1",
        receiver_id="RECEIVER1",
    )

    assert result.direction == "INBOUND"
    assert result.status == "RECEIVED"
    session.add.assert_called_once()
    session.flush.assert_awaited_once()
