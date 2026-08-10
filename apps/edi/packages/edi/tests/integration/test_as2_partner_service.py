import uuid
from unittest.mock import MagicMock

import pytest

from edi.adapters.uow_adapter import SqlAlchemyControlPlaneUnitOfWork
from edi.core.exceptions import (
    InvalidCertificateActionError,
    MissingCertificateError,
    PartnerNotFoundError,
)
from edi.core.services.as2_partner_service import AS2PartnerService
from edi.domain.models import (
    CreateAS2TradingPartnerCmd,
    RotateAS2CertificateCmd,
    UpdateAS2TradingPartnerCmd,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
def uow(db_session):
    db_session.info["session_type"] = "global"
    return SqlAlchemyControlPlaneUnitOfWork(global_session=db_session)


@pytest.fixture
def mock_vault():
    vault = MagicMock()
    vault.store_private_key.return_value = "fake_vault_ref"
    return vault


@pytest.mark.asyncio
async def test_update_as2_partner_not_found(uow):
    svc = AS2PartnerService(uow=uow)
    cmd = UpdateAS2TradingPartnerCmd(name="Test Update")

    with pytest.raises(PartnerNotFoundError):
        await svc.update_as2_partner(tenant_id="tenant-1", partner_id=str(uuid.uuid4()), cmd=cmd)


@pytest.mark.asyncio
async def test_create_and_update_as2_partner(uow):
    svc = AS2PartnerService(uow=uow)
    cmd = CreateAS2TradingPartnerCmd(name="Acme Corp", as2_id="ACME_AS2", is_local=True)

    partner = await svc.create_as2_partner("tenant-1", cmd)
    assert partner.name == "Acme Corp"
    assert partner.type == "AS2"

    update_cmd = UpdateAS2TradingPartnerCmd(name="Acme Corp Updated")
    updated_partner = await svc.update_as2_partner("tenant-1", partner.partner_id, update_cmd)

    assert updated_partner.name == "Acme Corp Updated"


@pytest.mark.asyncio
async def test_rotate_certificates_not_found(uow, mock_vault):
    svc = AS2PartnerService(uow=uow)
    cmd = RotateAS2CertificateCmd(action="generate")

    with pytest.raises(PartnerNotFoundError):
        await svc.rotate_certificates(
            tenant_id="tenant-1", partner_id=str(uuid.uuid4()), cmd=cmd, vault=mock_vault
        )


@pytest.mark.asyncio
async def test_rotate_certificates_invalid_action(uow, mock_vault):
    svc = AS2PartnerService(uow=uow)
    cmd = CreateAS2TradingPartnerCmd(name="Acme Corp", as2_id="ACME_AS2", is_local=True)
    partner = await svc.create_as2_partner("tenant-1", cmd)

    rotate_cmd = RotateAS2CertificateCmd(action="invalid_action")
    with pytest.raises(InvalidCertificateActionError):
        await svc.rotate_certificates(
            tenant_id="tenant-1", partner_id=partner.partner_id, cmd=rotate_cmd, vault=mock_vault
        )


@pytest.mark.asyncio
async def test_rotate_certificates_missing_cert_for_upload(uow, mock_vault):
    svc = AS2PartnerService(uow=uow)
    cmd = CreateAS2TradingPartnerCmd(name="Acme Corp", as2_id="ACME_AS2", is_local=True)
    partner = await svc.create_as2_partner("tenant-1", cmd)

    rotate_cmd = RotateAS2CertificateCmd(action="upload", public_cert_pem="only_public")
    with pytest.raises(
        MissingCertificateError,
        match="Both public_cert_pem and private_key_pem required for upload",
    ):
        await svc.rotate_certificates(
            tenant_id="tenant-1", partner_id=partner.partner_id, cmd=rotate_cmd, vault=mock_vault
        )


@pytest.mark.asyncio
async def test_rotate_certificates_remote_missing_public_cert(uow, mock_vault):
    svc = AS2PartnerService(uow=uow)
    cmd = CreateAS2TradingPartnerCmd(name="Remote Corp", as2_id="REMOTE_AS2", is_local=False)
    partner = await svc.create_as2_partner("tenant-1", cmd)

    rotate_cmd = RotateAS2CertificateCmd(action="upload", public_cert_pem=None)
    with pytest.raises(
        MissingCertificateError, match="public_cert_pem required for remote partners"
    ):
        await svc.rotate_certificates(
            tenant_id="tenant-1", partner_id=partner.partner_id, cmd=rotate_cmd, vault=mock_vault
        )


@pytest.mark.asyncio
async def test_rotate_certificates_generate_success(uow, mock_vault):
    svc = AS2PartnerService(uow=uow)
    cmd = CreateAS2TradingPartnerCmd(name="Acme Corp", as2_id="ACME_AS2", is_local=True)
    partner = await svc.create_as2_partner("tenant-1", cmd)

    rotate_cmd = RotateAS2CertificateCmd(action="generate")
    rotated_partner = await svc.rotate_certificates(
        tenant_id="tenant-1", partner_id=partner.partner_id, cmd=rotate_cmd, vault=mock_vault
    )

    assert rotated_partner.partner_id == partner.partner_id
    mock_vault.store_private_key.assert_called_once()
