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


@pytest.mark.asyncio
async def test_rotate_certificates_upload_success():
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
    mock_vault.store_private_key.return_value = "uploaded_vault_ref"

    cmd = RotateAS2CertificateCmd(
        action="upload",
        public_cert_pem="public_cert_content",
        private_key_pem="private_key_content",
    )

    result = await svc.rotate_certificates(
        tenant_id="1",
        partner_id=partner_id,
        cmd=cmd,
        vault=mock_vault,
    )

    assert result.partner_id == partner_id
    mock_vault.store_private_key.assert_called_once_with(
        private_key_pem=b"private_key_content", alias_prefix=f"{partner_id}_uploaded"
    )
    mock_repo.rotate_as2_certificates.assert_awaited_once_with(
        "1", partner_id, "public_cert_content", "uploaded_vault_ref"
    )


@pytest.mark.asyncio
async def test_rotate_certificates_upload_missing_pem():
    mock_repo = AsyncMock()
    mock_partner = MagicMock()
    mock_partner.is_local = True
    mock_repo.get_as2_partner.return_value = mock_partner

    svc = AS2PartnerService(uow=make_mock_uow(mock_repo))
    mock_vault = MagicMock()
    cmd = RotateAS2CertificateCmd(action="upload", public_cert_pem="only_public")

    with pytest.raises(
        ValueError, match=r"Both public_cert_pem and private_key_pem required for upload\."
    ):
        await svc.rotate_certificates("1", "partner_id", cmd, mock_vault)


@pytest.mark.asyncio
async def test_rotate_certificates_remote_missing_public_cert():
    mock_repo = AsyncMock()
    mock_partner = MagicMock()
    mock_partner.is_local = False
    mock_repo.get_as2_partner.return_value = mock_partner

    svc = AS2PartnerService(uow=make_mock_uow(mock_repo))
    mock_vault = MagicMock()
    cmd = RotateAS2CertificateCmd(action="upload", public_cert_pem=None)

    with pytest.raises(ValueError, match=r"public_cert_pem required for remote partners\."):
        await svc.rotate_certificates("1", "partner_id", cmd, mock_vault)


@pytest.mark.asyncio
async def test_rotate_certificates_compensation_on_failure():
    mock_repo = AsyncMock()
    mock_partner = MagicMock()
    mock_partner.is_local = True
    mock_partner.as2_id = "TEST_AS2"
    mock_repo.get_as2_partner.return_value = mock_partner
    # Make rotation fail to trigger compensation
    mock_repo.rotate_as2_certificates.side_effect = Exception("DB Error")

    svc = AS2PartnerService(uow=make_mock_uow(mock_repo))

    mock_vault = MagicMock()
    mock_vault.store_private_key.return_value = "new_vault_ref"

    cmd = RotateAS2CertificateCmd(action="generate")

    with pytest.raises(Exception, match="DB Error"):
        await svc.rotate_certificates("1", "partner_id", cmd, mock_vault)

    # Verify vault key was stored and then deleted in compensation
    mock_vault.store_private_key.assert_called_once()
    mock_vault.delete_secret.assert_called_once_with("new_vault_ref")


@pytest.mark.asyncio
async def test_rotate_certificates_invalid_action():
    mock_repo = AsyncMock()
    mock_partner = MagicMock()
    mock_repo.get_as2_partner.return_value = mock_partner

    svc = AS2PartnerService(uow=make_mock_uow(mock_repo))
    mock_vault = MagicMock()
    cmd = RotateAS2CertificateCmd(action="invalid_action")

    with pytest.raises(
        ValueError, match=r"Invalid action 'invalid_action'\. Must be 'generate' or 'upload'\."
    ):
        await svc.rotate_certificates("1", "partner_id", cmd, mock_vault)
