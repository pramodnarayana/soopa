"""
Replication Registry — Infrastructure Wiring of the Dependency Graph.

This module is the SINGLE SOURCE OF TRUTH for which entities are replicated
and what their FK dependencies are. It wires concrete SQLAlchemy model classes
into the EntitySpec declarative structure defined in config_sync_worker.domain.replication_graph.

This is an infrastructure concern (it imports ORM models), deliberately
separated from the pure domain types and algorithm in replication_graph.py.

Adding a new replicated entity:
    1. Import its global and tenant model classes below.
    2. Add its EntitySpec to REPLICATION_GRAPH with any FK dependencies listed.
    The generic replication driver (SqlAlchemyReplicationAdapter) will handle
    the rest — no changes to the adapter are required.
"""

from typing import Any

from database.models import Webhook as GlobalWebhook
from edi.adapters.outbound.database.models.control_plane import AS2Partner as GlobalAS2Partner
from edi.adapters.outbound.database.models.control_plane import (
    AS2Partnership as GlobalAS2Partnership,
)
from edi.adapters.outbound.database.models.control_plane import InboundRoute as GlobalInboundRoute
from edi.adapters.outbound.database.models.control_plane import (
    OutboundEdiHeader as GlobalOutboundEdiHeader,
)
from edi.adapters.outbound.database.models.control_plane import OutboundRoute as GlobalOutboundRoute
from edi.adapters.outbound.database.models.control_plane import SFTPPartner as GlobalSFTPPartner
from edi.adapters.outbound.database.models.data_plane import AS2Partner as TenantAS2Partner
from edi.adapters.outbound.database.models.data_plane import AS2Partnership as TenantAS2Partnership
from edi.adapters.outbound.database.models.data_plane import InboundRoute as TenantInboundRoute
from edi.adapters.outbound.database.models.data_plane import (
    OutboundEdiHeader as TenantOutboundEdiHeader,
)
from edi.adapters.outbound.database.models.data_plane import OutboundRoute as TenantOutboundRoute
from edi.adapters.outbound.database.models.data_plane import SFTPPartner as TenantSFTPPartner
from edi.adapters.outbound.database.models.data_plane import Webhook as TenantWebhook
from seedwork.domain.types import JsonDict

from config_sync_worker.domain.replication_graph import (
    EntityDependency,
    EntitySpec,
    validate_replication_graph,
)


def map_as2_partner(entity: Any) -> JsonDict:
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


def map_sftp_partner(entity: Any) -> JsonDict:
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


def map_webhook(entity: Any) -> JsonDict:
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


def map_outbound_edi_header(entity: Any) -> JsonDict:
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


def map_as2_partnership(entity: Any) -> JsonDict:
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


def map_inbound_route(entity: Any) -> JsonDict:
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


def map_outbound_route(entity: Any) -> JsonDict:
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


# ---------------------------------------------------------------------------
# Replication Graph
#
# Entities are declared without regard for order here — the topological_layers
# algorithm in replication_graph.py derives the correct insertion order at
# runtime from the declared dependencies.
# ---------------------------------------------------------------------------
REPLICATION_GRAPH: dict[str, EntitySpec] = {
    # ---- Leaf entities (no FK dependencies) ----
    "as2_partner": EntitySpec(
        global_model=GlobalAS2Partner,
        tenant_model=TenantAS2Partner,
        mapper=map_as2_partner,
        include_shared=True,
        dependencies=[],
    ),
    "sftp_partner": EntitySpec(
        global_model=GlobalSFTPPartner,
        tenant_model=TenantSFTPPartner,
        mapper=map_sftp_partner,
        include_shared=False,
        dependencies=[],
    ),
    "webhook": EntitySpec(
        global_model=GlobalWebhook,
        tenant_model=TenantWebhook,
        mapper=map_webhook,
        include_shared=False,
        dependencies=[],
    ),
    "outbound_edi_header": EntitySpec(
        global_model=GlobalOutboundEdiHeader,
        tenant_model=TenantOutboundEdiHeader,
        mapper=map_outbound_edi_header,
        include_shared=False,
        dependencies=[],
    ),
    # ---- Entities with FK dependencies (layer 1) ----
    "as2_partnership": EntitySpec(
        global_model=GlobalAS2Partnership,
        tenant_model=TenantAS2Partnership,
        mapper=map_as2_partnership,
        include_shared=True,
        # FK: local_partner_id → as2_partners.id
        #     remote_partner_id → as2_partners.id
        # Both must be satisfied before the partnership can be inserted.
        dependencies=[
            EntityDependency(
                fk_attr="local_partner_id",
                target_key="as2_partner",
            ),
            EntityDependency(
                fk_attr="remote_partner_id",
                target_key="as2_partner",
            ),
        ],
    ),
    "inbound_route": EntitySpec(
        global_model=GlobalInboundRoute,
        tenant_model=TenantInboundRoute,
        mapper=map_inbound_route,
        include_shared=False,
        # CHECK constraint: exactly ONE of these three FK columns is non-null.
        # All three are listed; the driver skips null values automatically.
        # FK: as2_partner_id → as2_partners.id
        #     sftp_partner_id → sftp_partners.id
        #     webhook_id      → webhooks.id
        dependencies=[
            EntityDependency(
                fk_attr="as2_partner_id",
                target_key="as2_partner",
            ),
            EntityDependency(
                fk_attr="sftp_partner_id",
                target_key="sftp_partner",
            ),
            EntityDependency(
                fk_attr="webhook_id",
                target_key="webhook",
            ),
        ],
    ),
    "outbound_route": EntitySpec(
        global_model=GlobalOutboundRoute,
        tenant_model=TenantOutboundRoute,
        mapper=map_outbound_route,
        include_shared=False,
        # CHECK constraint: exactly ONE of these two FK columns is non-null.
        # FK: as2_partner_id  → as2_partners.id
        #     sftp_partner_id → sftp_partners.id
        dependencies=[
            EntityDependency(
                fk_attr="as2_partner_id",
                target_key="as2_partner",
            ),
            EntityDependency(
                fk_attr="sftp_partner_id",
                target_key="sftp_partner",
            ),
        ],
    ),
}

# Fail fast at startup if graph structure violates invariants
validate_replication_graph(REPLICATION_GRAPH)
