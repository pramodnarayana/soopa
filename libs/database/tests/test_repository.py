from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from database.models import TradingPartner
from database.repository import (
    AS2PayloadRepository,
    HostIdentityRepository,
    TradingPartnerRepository,
)

pytestmark = pytest.mark.asyncio


@patch("database.repository.get_tenant_id", return_value=123)
async def test_trading_partner_repository_find_by_as2_id(mock_get_tenant_id) -> None:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_partner = TradingPartner(as2_id="TEST-ID", public_cert_pem="cert")
    mock_result.scalar_one_or_none.return_value = mock_partner
    session.execute.return_value = mock_result

    repo = TradingPartnerRepository(session)
    result = await repo.find_by_as2_id("TEST-ID")

    assert result == mock_partner
    session.execute.assert_called_once()


@patch("database.repository.get_tenant_id", return_value=123)
async def test_trading_partner_repository_get_public_certificate(mock_get_tenant_id) -> None:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_partner = TradingPartner(as2_id="TEST-ID", public_cert_pem="cert_data")
    mock_result.scalar_one_or_none.return_value = mock_partner
    session.execute.return_value = mock_result

    repo = TradingPartnerRepository(session)
    cert = await repo.get_public_certificate("TEST-ID")

    assert cert == b"cert_data"


@patch("database.repository.get_tenant_id", return_value=None)
async def test_repository_raises_error_when_no_tenant(mock_get_tenant_id) -> None:
    repo = TradingPartnerRepository(AsyncMock())
    with pytest.raises(RuntimeError, match="Database queries require an active tenant context."):
        await repo.find_by_as2_id("TEST")


@patch("database.repository.get_tenant_id", return_value=123)
async def test_host_identity_repository_get_host_private_key(mock_get_tenant_id) -> None:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_host = TradingPartner(is_host_identity=True, private_key_pem="private_key_data")
    mock_result.scalar_one_or_none.return_value = mock_host
    session.execute.return_value = mock_result

    repo = HostIdentityRepository(session)
    key = await repo.get_host_private_key()

    assert key == b"private_key_data"


@patch("database.repository.get_tenant_id", return_value=123)
async def test_as2_payload_repository_save_payload(mock_get_tenant_id) -> None:
    session = AsyncMock()
    repo = AS2PayloadRepository(session)

    result = await repo.save_payload(
        message_id="msg-123",
        direction="INBOUND",
        as2_from="SENDER",
        as2_to="RECEIVER",
        status="processed",
        payload_storage_uri="s3://bucket/test.bin",
    )

    assert result.message_id == "msg-123"
    session.add.assert_called_once()
    session.flush.assert_called_once()
