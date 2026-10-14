from collections.abc import Mapping

from database.models import Webhook
from edi.adapters.outbound.database.models.control_plane import (
    AS2Partner,
    AS2Partnership,
    InboundRoute,
    OutboundEdiHeader,
    OutboundRoute,
    SFTPPartner,
)


def map_as2_partner(entity: AS2Partner) -> Mapping[str, object]:
    return {
        "id": entity.id,
        "tenant_id": entity.tenant_id,
        "name": entity.name,
        "as2_id": entity.as2_id,
        "public_cert_pem": entity.public_cert_pem,
        "public_cert_vault_ref": entity.public_cert_vault_ref,
        "private_key_vault_ref": entity.private_key_vault_ref,
        "prev_public_cert_pem": entity.prev_public_cert_pem,
        "prev_public_cert_vault_ref": entity.prev_public_cert_vault_ref,
        "prev_private_key_vault_ref": entity.prev_private_key_vault_ref,
        "url": entity.url,
        "is_local": entity.is_local,
        "active": entity.active,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def map_sftp_partner(entity: SFTPPartner) -> Mapping[str, object]:
    return {
        "id": entity.id,
        "tenant_id": entity.tenant_id,
        "name": entity.name,
        "host": entity.host,
        "port": entity.port,
        "username": entity.username,
        "host_key": entity.host_key,
        "inbound_remote_path": entity.inbound_remote_path,
        "outbound_remote_path": entity.outbound_remote_path,
        "password_encrypted": entity.password_encrypted,
        "credentials_vault_ref": entity.credentials_vault_ref,
        "active": entity.active,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def map_webhook(entity: Webhook) -> Mapping[str, object]:
    return {
        "id": entity.id,
        "tenant_id": entity.tenant_id,
        "name": entity.name,
        "url": entity.url,
        "auth_header_vault_ref": entity.auth_header_vault_ref,
        "active": entity.active,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def map_outbound_edi_header(entity: OutboundEdiHeader) -> Mapping[str, object]:
    return {
        "id": entity.id,
        "tenant_id": entity.tenant_id,
        "trading_partner_id": entity.trading_partner_id,
        "name": entity.name,
        "isa_sender_id": entity.isa_sender_id,
        "isa_sender_qualifier": entity.isa_sender_qualifier,
        "isa_receiver_id": entity.isa_receiver_id,
        "isa_receiver_qualifier": entity.isa_receiver_qualifier,
        "gs_sender_id": entity.gs_sender_id,
        "gs_receiver_id": entity.gs_receiver_id,
        "transaction_type": entity.transaction_type,
        "default_standard": entity.default_standard,
        "default_version": entity.default_version,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def map_as2_partnership(entity: AS2Partnership) -> Mapping[str, object]:
    return {
        "id": entity.id,
        "tenant_id": entity.tenant_id,
        "local_partner_id": entity.local_partner_id,
        "remote_partner_id": entity.remote_partner_id,
        "name": entity.name,
        "credentials_vault_ref": entity.credentials_vault_ref,
        "mdn_type": entity.mdn_type,
        "mdn_url": entity.mdn_url,
        "encryption_algorithm": entity.encryption_algorithm,
        "signature_algorithm": entity.signature_algorithm,
        "advanced_flags": entity.advanced_flags,
        "active": entity.active,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def map_inbound_route(entity: InboundRoute) -> Mapping[str, object]:
    return {
        "id": entity.id,
        "tenant_id": entity.tenant_id,
        "name": entity.name,
        "trading_partner_id": entity.trading_partner_id,
        "isa_sender_id": entity.isa_sender_id,
        "isa_receiver_id": entity.isa_receiver_id,
        "gs_sender_id": entity.gs_sender_id,
        "gs_receiver_id": entity.gs_receiver_id,
        "transaction_type": entity.transaction_type,
        "processing_mode": entity.processing_mode,
        "connection_type": entity.connection_type,
        "active": entity.active,
        "webhook_id": entity.webhook_id,
        "as2_partner_id": entity.as2_partner_id,
        "sftp_partner_id": entity.sftp_partner_id,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def map_outbound_route(entity: OutboundRoute) -> Mapping[str, object]:
    return {
        "id": entity.id,
        "tenant_id": entity.tenant_id,
        "trading_partner_id": entity.trading_partner_id,
        "name": entity.name,
        "connection_type": entity.connection_type,
        "webhook_id": entity.webhook_id,
        "active": entity.active,
        "as2_partner_id": entity.as2_partner_id,
        "sftp_partner_id": entity.sftp_partner_id,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }
