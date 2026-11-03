"""Unit tests for EDI Partner & Partnership Behavioral Aggregates under Red-Green-Refactor.

Verifies:
- AS2Partner: create, update (with no-op guard), rotate_certificate, activate, deactivate, mark_deleted
- AS2Partnership: create, update (reflection-free with no-op guard), activate, deactivate, mark_deleted
- SFTPPartner: create (XOR credential exclusivity), update (XOR credential exclusivity + no-op guard), activate, deactivate, mark_deleted
- Timezone-aware UTC timestamps and AggregateRoot identity-based equality across all partner aggregates
- All methods return Result[Self, EdiPartnerError] and record ProvisioningEvent internally
"""

from __future__ import annotations

from dataclasses import replace

from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from edi.domain.constants import EdiIdPrefix
from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.domain.exceptions import EdiErrorCode, EdiPartnerError
from edi.domain.partner.as2.enums import EncryptionAlgorithm, MDNType, SignatureAlgorithm
from edi.domain.partner.as2.partner import AS2Partner
from edi.domain.partner.as2.partnership import AS2Partnership
from edi.domain.partner.sftp.partner import SFTPPartner


def test_as2_partner_create_update_activate_rotate_and_delete() -> None:
    tenant_id = generate_id(EdiIdPrefix.TENANT)
    create_idem = generate_id(SystemIdPrefix.IDEMPOTENCY)
    rotate_idem = generate_id(SystemIdPrefix.IDEMPOTENCY)
    delete_idem = generate_id(SystemIdPrefix.IDEMPOTENCY)

    bad = AS2Partner.create(tenant_id=tenant_id, name="  ", as2_id="ACME")
    assert bad.is_err
    assert isinstance(bad.unwrap_err(), EdiPartnerError)
    assert bad.unwrap_err().code == EdiErrorCode.VALIDATION_FAILED

    res = AS2Partner.create(
        tenant_id=tenant_id,
        name="Acme Corp",
        as2_id="ACME_AS2",
        is_local=True,
        public_cert_pem="-----BEGIN CERTIFICATE-----\nOLD\n-----END CERTIFICATE-----",
        private_key_vault_ref="vault://keys/old",
        idempotency_key=create_idem,
    )
    assert res.is_ok
    partner = res.unwrap()
    assert partner.id.startswith("edi_as2_tp_")
    assert partner.active is False
    assert partner.created_at.tzinfo is not None
    assert partner.updated_at.tzinfo is not None

    # Reference identity (eq=False disables Value-Object attribute equality and preserves hashability)
    cloned_partner = replace(partner)
    assert partner != cloned_partner
    assert isinstance(hash(partner), int)

    events = partner.pull_domain_events()
    assert len(events) == 1
    assert isinstance(events[0], ProvisioningEvent)
    assert events[0].event_type == EdiEventType.edi_as2_partner_created
    assert events[0].idempotency_key == create_idem

    # No-op update emits zero events
    noop_upd = partner.update(name="Acme Corp")
    assert noop_upd.is_ok
    assert len(partner.pull_domain_events()) == 0

    # Activate / Deactivate
    assert partner.activate().is_ok
    assert partner.active is True
    assert partner.activate().unwrap_err().code == EdiErrorCode.PARTNER_ALREADY_ACTIVE
    assert partner.deactivate().is_ok
    assert partner.active is False
    assert partner.deactivate().unwrap_err().code == EdiErrorCode.PARTNER_ALREADY_INACTIVE
    _ = partner.pull_domain_events()

    # Rotate certificate: local partner requires private_key_vault_ref
    bad_rot = partner.rotate_certificate(
        public_cert_pem="-----BEGIN CERTIFICATE-----\nNEW\n-----END CERTIFICATE-----",
        private_key_vault_ref=None,
    )
    assert bad_rot.is_err
    assert bad_rot.unwrap_err().code == EdiErrorCode.MISSING_CERTIFICATE

    rot_ok = partner.rotate_certificate(
        public_cert_pem="-----BEGIN CERTIFICATE-----\nNEW\n-----END CERTIFICATE-----",
        private_key_vault_ref="vault://keys/new",
        idempotency_key=rotate_idem,
    )
    assert rot_ok.is_ok
    assert (
        partner.prev_public_cert_pem
        == "-----BEGIN CERTIFICATE-----\nOLD\n-----END CERTIFICATE-----"
    )
    assert partner.prev_private_key_vault_ref == "vault://keys/old"
    assert partner.public_cert_pem == "-----BEGIN CERTIFICATE-----\nNEW\n-----END CERTIFICATE-----"
    assert partner.private_key_vault_ref == "vault://keys/new"
    rot_events = partner.pull_domain_events()
    assert len(rot_events) == 1
    assert isinstance(rot_events[0], ProvisioningEvent)
    assert rot_events[0].event_type == EdiEventType.edi_as2_partner_updated
    assert rot_events[0].idempotency_key == rotate_idem

    # Update & Delete
    upd_ok = partner.update(name="Acme International", url="https://as2.acme.com", active=True)
    assert upd_ok.is_ok
    assert partner.name == "Acme International"
    assert partner.url == "https://as2.acme.com"
    assert partner.active is True
    _ = partner.pull_domain_events()

    del_ok = partner.mark_deleted(idempotency_key=delete_idem)
    assert del_ok.is_ok
    assert partner.active is False
    del_events = partner.pull_domain_events()
    assert len(del_events) == 1
    assert isinstance(del_events[0], ProvisioningEvent)
    assert del_events[0].event_type == EdiEventType.edi_as2_partner_deleted


def test_as2_partnership_lifecycle_without_reflection() -> None:
    tenant_id = generate_id(EdiIdPrefix.TENANT)
    same_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER)
    local_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER)
    remote_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER)

    same_partner = AS2Partnership.create(
        tenant_id=tenant_id,
        name="Self Link",
        local_partner_id=same_id,
        remote_partner_id=same_id,
    )
    assert same_partner.is_err
    assert same_partner.unwrap_err().code == EdiErrorCode.VALIDATION_FAILED

    res = AS2Partnership.create(
        tenant_id=tenant_id,
        name="Tenant <-> Walmart",
        local_partner_id=local_id,
        remote_partner_id=remote_id,
        mdn_type=MDNType.SYNC,
        encryption_algorithm=EncryptionAlgorithm.AES256,
        signature_algorithm=SignatureAlgorithm.SHA256,
    )
    assert res.is_ok
    ps = res.unwrap()
    assert ps.active is True
    assert ps.created_at.tzinfo is not None
    assert ps.updated_at.tzinfo is not None
    assert ps != replace(ps)
    assert isinstance(hash(ps), int)
    events = ps.pull_domain_events()
    assert len(events) == 1
    assert isinstance(events[0], ProvisioningEvent)
    assert events[0].event_type == EdiEventType.edi_as2_partnership_created

    # No-op update emits zero events
    noop_upd = ps.update(name="Tenant <-> Walmart")
    assert noop_upd.is_ok
    assert len(ps.pull_domain_events()) == 0

    upd_bad = ps.update(name="   ")
    assert upd_bad.is_err

    upd_ok = ps.update(
        name="Updated Partnership",
        mdn_url="https://mdn.example.com",
        active=False,
    )
    assert upd_ok.is_ok
    assert ps.name == "Updated Partnership"
    assert ps.mdn_url == "https://mdn.example.com"
    assert ps.active is False
    upd_events = ps.pull_domain_events()
    assert len(upd_events) == 1
    assert isinstance(upd_events[0], ProvisioningEvent)
    assert upd_events[0].event_type == EdiEventType.edi_as2_partnership_updated

    assert ps.activate().is_ok
    assert ps.deactivate().is_ok
    _ = ps.pull_domain_events()

    del_ok = ps.mark_deleted()
    assert del_ok.is_ok
    del_events = ps.pull_domain_events()
    assert len(del_events) == 1
    assert isinstance(del_events[0], ProvisioningEvent)
    assert del_events[0].event_type == EdiEventType.edi_as2_partnership_deleted


def test_sftp_partner_lifecycle_and_credential_exclusivity() -> None:
    tenant_id = generate_id(EdiIdPrefix.TENANT)
    fixture_cipher = "fixture_ciphertext_v1"

    bad_port = SFTPPartner.create(
        tenant_id=tenant_id,
        name="SFTP 1",
        host="sftp.example.com",
        port=70000,
        username="edi_user",
        credentials_vault_ref="vault://sftp/1",
    )
    assert bad_port.is_err
    assert bad_port.unwrap_err().code == EdiErrorCode.VALIDATION_FAILED

    # Create fails when NEITHER credential source is provided
    create_neither = SFTPPartner.create(
        tenant_id=tenant_id,
        name="SFTP Neither",
        host="sftp.example.com",
        port=22,
        username="edi_user",
    )
    assert create_neither.is_err
    assert create_neither.unwrap_err().code == EdiErrorCode.VALIDATION_FAILED

    # Create fails when BOTH credential sources are provided
    create_both = SFTPPartner.create(
        tenant_id=tenant_id,
        name="SFTP Both",
        host="sftp.example.com",
        port=22,
        username="edi_user",
        password_encrypted=fixture_cipher,
        credentials_vault_ref="vault://sftp/1",
    )
    assert create_both.is_err
    assert create_both.unwrap_err().code == EdiErrorCode.VALIDATION_FAILED

    res = SFTPPartner.create(
        tenant_id=tenant_id,
        name="SFTP Target",
        host="sftp.example.com",
        port=22,
        username="edi_user",
        credentials_vault_ref="vault://sftp/1",
    )
    assert res.is_ok
    sftp = res.unwrap()
    assert sftp.active is False
    assert sftp.created_at.tzinfo is not None
    assert sftp.updated_at.tzinfo is not None
    assert sftp != replace(sftp)
    assert isinstance(hash(sftp), int)
    events = sftp.pull_domain_events()
    assert len(events) == 1
    assert isinstance(events[0], ProvisioningEvent)
    assert events[0].event_type == EdiEventType.edi_sftp_partner_created

    # No-op update emits zero events
    noop_upd = sftp.update(host="sftp.example.com")
    assert noop_upd.is_ok
    assert len(sftp.pull_domain_events()) == 0

    # Cannot have BOTH password_encrypted and credentials_vault_ref
    both_creds = sftp.update(password_encrypted=fixture_cipher)
    assert both_creds.is_err
    assert both_creds.unwrap_err().code == EdiErrorCode.VALIDATION_FAILED

    # Cannot have NEITHER password_encrypted nor credentials_vault_ref
    neither_creds = sftp.update(credentials_vault_ref="")
    assert neither_creds.is_err
    assert neither_creds.unwrap_err().code == EdiErrorCode.VALIDATION_FAILED

    # Switching cleanly from vault ref to encrypted password works
    upd_ok = sftp.update(
        host="sftp2.example.com",
        credentials_vault_ref=None,
        password_encrypted=fixture_cipher,
        active=True,
    )
    assert upd_ok.is_ok
    assert sftp.host == "sftp2.example.com"
    assert sftp.credentials_vault_ref is None
    assert sftp.password_encrypted == fixture_cipher
    assert sftp.active is True
    upd_events = sftp.pull_domain_events()
    assert len(upd_events) == 1
    assert isinstance(upd_events[0], ProvisioningEvent)
    assert upd_events[0].event_type == EdiEventType.edi_sftp_partner_updated

    del_ok = sftp.mark_deleted()
    assert del_ok.is_ok
    del_events = sftp.pull_domain_events()
    assert len(del_events) == 1
    assert isinstance(del_events[0], ProvisioningEvent)
    assert del_events[0].event_type == EdiEventType.edi_sftp_partner_deleted
