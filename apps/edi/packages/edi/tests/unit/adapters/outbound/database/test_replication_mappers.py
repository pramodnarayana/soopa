import os
from datetime import UTC, datetime

from database.models import Webhook

from edi.adapters.outbound.database.models.control_plane import (
    AS2Partner,
    AS2Partnership,
    InboundRoute,
    OutboundEdiHeader,
    OutboundRoute,
    SFTPPartner,
)
from edi.adapters.outbound.database.replication_mappers import (
    map_as2_partner,
    map_as2_partnership,
    map_inbound_route,
    map_outbound_edi_header,
    map_outbound_route,
    map_sftp_partner,
    map_webhook,
)


def test_map_as2_partner() -> None:
    entity = AS2Partner(
        id="as2_p_123",
        tenant_id="tenant_abc",
        name="Acme AS2 Partner",
        as2_id="ACME_AS2",
        public_cert_pem="-----BEGIN CERTIFICATE-----\n...",
        public_cert_vault_ref="vault://cert/1",
        private_key_vault_ref="vault://key/1",
        prev_public_cert_pem="-----BEGIN CERTIFICATE-----\nOLD...",
        prev_public_cert_vault_ref="vault://cert/old",
        prev_private_key_vault_ref="vault://key/old",
        url="https://as2.acme.com/inbox",
        is_local=False,
        active=True,
        created_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
    )
    result = map_as2_partner(entity)

    assert result == {
        "id": "as2_p_123",
        "tenant_id": "tenant_abc",
        "name": "Acme AS2 Partner",
        "as2_id": "ACME_AS2",
        "public_cert_pem": "-----BEGIN CERTIFICATE-----\n...",
        "public_cert_vault_ref": "vault://cert/1",
        "private_key_vault_ref": "vault://key/1",
        "prev_public_cert_pem": "-----BEGIN CERTIFICATE-----\nOLD...",
        "prev_public_cert_vault_ref": "vault://cert/old",
        "prev_private_key_vault_ref": "vault://key/old",
        "url": "https://as2.acme.com/inbox",
        "is_local": False,
        "active": True,
        "created_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
    }


def test_map_sftp_partner() -> None:
    entity = SFTPPartner(
        id="sftp_p_123",
        tenant_id="tenant_abc",
        name="Acme SFTP Partner",
        host="sftp.acme.com",
        port=22,
        username="acme_user",
        host_key="ssh-rsa AAAAB3NzaC1yc2E...",
        inbound_remote_path="/inbox",
        outbound_remote_path="/outbox",
        password_encrypted=None,
        credentials_vault_ref="vault://sftp/creds",
        active=True,
        created_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
    )
    result = map_sftp_partner(entity)

    assert result == {
        "id": "sftp_p_123",
        "tenant_id": "tenant_abc",
        "name": "Acme SFTP Partner",
        "host": "sftp.acme.com",
        "port": 22,
        "username": "acme_user",
        "host_key": "ssh-rsa AAAAB3NzaC1yc2E...",
        "inbound_remote_path": "/inbox",
        "outbound_remote_path": "/outbox",
        "password_encrypted": None,
        "credentials_vault_ref": "vault://sftp/creds",
        "active": True,
        "created_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
    }

    cipher_val = f"cipher_{os.environ.get('DUMMY_VALUE', 'val')}"
    entity_with_pass = SFTPPartner(
        id="sftp_p_123",
        tenant_id="tenant_abc",
        name="Acme SFTP Partner",
        host="sftp.acme.com",
        port=22,
        username="acme_user",
        host_key=None,
        inbound_remote_path="/inbox",
        outbound_remote_path="/outbox",
        password_encrypted=cipher_val,
        credentials_vault_ref=None,
        active=True,
        created_at=None,
        updated_at=None,
    )
    assert map_sftp_partner(entity_with_pass)["password_encrypted"] == cipher_val


def test_map_webhook() -> None:
    entity = Webhook(
        id="wh_123",
        tenant_id="tenant_abc",
        name="Acme Webhook",
        url="https://api.acme.com/webhook",
        auth_header_vault_ref="vault://wh/auth",
        active=True,
        created_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
    )
    result = map_webhook(entity)

    assert result == {
        "id": "wh_123",
        "tenant_id": "tenant_abc",
        "name": "Acme Webhook",
        "url": "https://api.acme.com/webhook",
        "auth_header_vault_ref": "vault://wh/auth",
        "active": True,
        "created_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
    }


def test_map_outbound_edi_header() -> None:
    entity = OutboundEdiHeader(
        id="header_123",
        tenant_id="tenant_abc",
        trading_partner_id="tp_123",
        name="Acme 850 Header",
        isa_sender_id="FLOWWOLF",
        isa_sender_qualifier="ZZ",
        isa_receiver_id="ACME",
        isa_receiver_qualifier="01",
        gs_sender_id="FLOWWOLF",
        gs_receiver_id="ACME",
        transaction_type="850",
        default_standard="X12",
        default_version="004010",
        created_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
    )
    result = map_outbound_edi_header(entity)

    assert result == {
        "id": "header_123",
        "tenant_id": "tenant_abc",
        "trading_partner_id": "tp_123",
        "name": "Acme 850 Header",
        "isa_sender_id": "FLOWWOLF",
        "isa_sender_qualifier": "ZZ",
        "isa_receiver_id": "ACME",
        "isa_receiver_qualifier": "01",
        "gs_sender_id": "FLOWWOLF",
        "gs_receiver_id": "ACME",
        "transaction_type": "850",
        "default_standard": "X12",
        "default_version": "004010",
        "created_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
    }


def test_map_as2_partnership() -> None:
    entity = AS2Partnership(
        id="ship_123",
        tenant_id="tenant_abc",
        local_partner_id="as2_local_1",
        remote_partner_id="as2_remote_1",
        name="Local to Acme",
        credentials_vault_ref="vault://partnership/creds",
        mdn_type="SYNC",
        mdn_url="https://local.flowwolf.io/as2/mdn",
        encryption_algorithm="3DES",
        signature_algorithm="SHA-256",
        advanced_flags={"compress": True},
        active=True,
        created_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
    )
    result = map_as2_partnership(entity)

    assert result == {
        "id": "ship_123",
        "tenant_id": "tenant_abc",
        "local_partner_id": "as2_local_1",
        "remote_partner_id": "as2_remote_1",
        "name": "Local to Acme",
        "credentials_vault_ref": "vault://partnership/creds",
        "mdn_type": "SYNC",
        "mdn_url": "https://local.flowwolf.io/as2/mdn",
        "encryption_algorithm": "3DES",
        "signature_algorithm": "SHA-256",
        "advanced_flags": {"compress": True},
        "active": True,
        "created_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
    }


def test_map_inbound_route() -> None:
    entity = InboundRoute(
        id="ir_123",
        tenant_id="tenant_abc",
        name="Acme Inbound 850",
        trading_partner_id="tp_123",
        isa_sender_id="ACME",
        isa_receiver_id="FLOWWOLF",
        gs_sender_id="ACME",
        gs_receiver_id="FLOWWOLF",
        transaction_type="850",
        processing_mode="TRANSLATE",
        connection_type="AS2",
        active=True,
        webhook_id=None,
        as2_partner_id="as2_p_123",
        sftp_partner_id=None,
        created_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
    )
    result = map_inbound_route(entity)

    assert result == {
        "id": "ir_123",
        "tenant_id": "tenant_abc",
        "name": "Acme Inbound 850",
        "trading_partner_id": "tp_123",
        "isa_sender_id": "ACME",
        "isa_receiver_id": "FLOWWOLF",
        "gs_sender_id": "ACME",
        "gs_receiver_id": "FLOWWOLF",
        "transaction_type": "850",
        "processing_mode": "TRANSLATE",
        "connection_type": "AS2",
        "active": True,
        "webhook_id": None,
        "as2_partner_id": "as2_p_123",
        "sftp_partner_id": None,
        "created_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
    }


def test_map_outbound_route() -> None:
    entity = OutboundRoute(
        id="or_123",
        tenant_id="tenant_abc",
        trading_partner_id="tp_123",
        name="Acme Outbound 810",
        connection_type="SFTP",
        webhook_id=None,
        active=True,
        as2_partner_id=None,
        sftp_partner_id="sftp_p_123",
        created_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
    )
    result = map_outbound_route(entity)

    assert result == {
        "id": "or_123",
        "tenant_id": "tenant_abc",
        "trading_partner_id": "tp_123",
        "name": "Acme Outbound 810",
        "connection_type": "SFTP",
        "webhook_id": None,
        "active": True,
        "as2_partner_id": None,
        "sftp_partner_id": "sftp_p_123",
        "created_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
    }
