from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from edi.core.services.as2_partner_service import AS2PartnerService
from edi.domain.models import RotateAS2CertificateCmd, UpdateAS2TradingPartnerCmd


def make_mock_uow(mock_repo: AsyncMock) -> MagicMock:
    uow = MagicMock()
    uow.as2_partners = mock_repo
    uow.control_plane_outbox = mock_repo
    uow.global_session = mock_repo
    return uow


@pytest.mark.asyncio
async def test_update_as2_partner_not_found():
    mock_repo = AsyncMock()
    mock_repo.get_as2_partner.return_value = None

    svc = AS2PartnerService(uow=make_mock_uow(mock_repo))
    cmd = UpdateAS2TradingPartnerCmd(name="Test")

    with pytest.raises(ValueError, match="Partner not found after update"):
        await svc.update_as2_partner("1", uuid4(), cmd)


@pytest.mark.asyncio
async def test_rotate_certificates_success():
    mock_repo = AsyncMock()
    mock_partner = MagicMock()
    mock_partner.name = "Test Partner"
    mock_partner.active = True
    mock_partner.is_local = True
    mock_partner.as2_id = "TEST_AS2"
    mock_repo.get_as2_partner.return_value = mock_partner

    svc = AS2PartnerService(uow=make_mock_uow(mock_repo))
    partner_id = str(uuid4())

    mock_vault = MagicMock()
    mock_vault.store_private_key.return_value = "new_vault_ref"

    cmd = RotateAS2CertificateCmd(action="generate")

    result = await svc.rotate_certificates(
        tenant_id="1",
        partner_id=partner_id,
        cmd=cmd,
        vault=mock_vault,
    )

    assert result.partner_id == partner_id
    assert result.name == "Test Partner"
    assert result.status == "ACTIVE"

    mock_repo.rotate_as2_certificates.assert_awaited_once()
    mock_repo.publish_outbox_event.assert_awaited_once()
    mock_vault.store_private_key.assert_called_once()


@pytest.mark.asyncio
async def test_rotate_certificates_not_found():
    mock_repo = AsyncMock()
    mock_repo.get_as2_partner.return_value = None

    svc = AS2PartnerService(uow=make_mock_uow(mock_repo))

    mock_vault = MagicMock()
    cmd = RotateAS2CertificateCmd(action="generate")

    with pytest.raises(ValueError, match="Partner not found"):
        await svc.rotate_certificates(
            tenant_id="1", partner_id=str(uuid4()), cmd=cmd, vault=mock_vault
        )
