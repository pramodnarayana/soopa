import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from database.models import TenantConnection, TenantTradingPartner
from database.repository import (
    ConnectionRepository,
    EdiMessageRepository,
    TradingPartnerRepository,
)

pytestmark = pytest.mark.asyncio


@patch("database.repository.get_tenant_id", return_value=123)
async def test_trading_partner_repository_find_by_as2_id(mock_get_tenant_id: Any) -> None:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_partner = TenantTradingPartner(as2_id="TEST-ID", partner_name="Test")
    mock_result.scalar_one_or_none.return_value = mock_partner
    session.execute.return_value = mock_result

    repo = TradingPartnerRepository(session)
    result = await repo.find_by_as2_id("TEST-ID")

    assert result == mock_partner
    session.execute.assert_called_once()


@patch("database.repository.get_tenant_id", return_value=None)
async def test_repository_raises_error_when_no_tenant(mock_get_tenant_id: Any) -> None:
    repo = TradingPartnerRepository(AsyncMock())
    with pytest.raises(RuntimeError, match="Database queries require an active tenant context."):
        await repo.find_by_as2_id("TEST")


@patch("database.repository.get_tenant_id", return_value=123)
async def test_connection_repository_find_by_partner_id(mock_get_tenant_id: Any) -> None:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_conn = TenantConnection(connection_type="AS2", credentials_vault_ref="vault-123")
    mock_result.scalar_one_or_none.return_value = mock_conn
    session.execute.return_value = mock_result

    repo = ConnectionRepository(session)
    result = await repo.find_by_partner_id(uuid.uuid4(), "AS2")

    assert result == mock_conn
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
        trading_partner_id=uuid.uuid4(),
        s3_key="s3://bucket/test.bin",
    )

    assert result.direction == "INBOUND"
    assert result.status == "RECEIVED"
    session.add.assert_called_once()
    session.flush.assert_awaited_once()
