from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from api.core.services.as2_partner_service import AS2PartnerService
from api.domain.models import UpdateAS2TradingPartnerCmd


@pytest.mark.asyncio
async def test_update_as2_partner_not_found():
    mock_repo = AsyncMock()
    mock_repo.get_as2_partner.return_value = None

    svc = AS2PartnerService(mock_repo)
    cmd = UpdateAS2TradingPartnerCmd(name="Test")

    with pytest.raises(ValueError, match="Partner not found after update"):
        await svc.update_as2_partner(1, uuid4(), cmd)


@pytest.mark.asyncio
async def test_rotate_certificates_success():
    mock_repo = AsyncMock()
    mock_partner = AsyncMock()
    mock_partner.name = "Test Partner"
    mock_partner.active = True
    mock_repo.get_as2_partner.return_value = mock_partner

    svc = AS2PartnerService(mock_repo)
    partner_id = uuid4()

    result = await svc.rotate_certificates(
        tenant_id=1, partner_id=partner_id, new_public_cert="cert", new_private_key_vault_ref="ref"
    )

    assert result.partner_id == partner_id
    assert result.name == "Test Partner"
    assert result.status == "ACTIVE"

    mock_repo.rotate_as2_certificates.assert_awaited_once_with(1, partner_id, "cert", "ref")
    mock_repo.create_outbox_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_rotate_certificates_not_found():
    mock_repo = AsyncMock()
    mock_repo.get_as2_partner.return_value = None

    svc = AS2PartnerService(mock_repo)

    with pytest.raises(ValueError, match="Partner not found after certificate rotation"):
        await svc.rotate_certificates(1, uuid4(), "cert", None)
