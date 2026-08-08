"""
Replication Registry — Infrastructure Wiring of the Dependency Graph.

This module is the SINGLE SOURCE OF TRUTH for which entities are replicated
and what their FK dependencies are. It wires concrete SQLAlchemy model classes
into the EntitySpec declarative structure defined in worker.core.replication_graph.

This is an infrastructure concern (it imports ORM models), deliberately
separated from the pure domain types and algorithm in replication_graph.py.

Adding a new replicated entity:
    1. Import its global and tenant model classes below.
    2. Add its EntitySpec to REPLICATION_GRAPH with any FK dependencies listed.
    The generic replication driver (SqlAlchemyReplicationAdapter) will handle
    the rest — no changes to the adapter are required.
"""

from database.models.control_plane import AS2Partner as GlobalAS2Partner
from database.models.control_plane import AS2Partnership as GlobalAS2Partnership
from database.models.control_plane import InboundRoute as GlobalInboundRoute
from database.models.control_plane import OutboundEdiHeader as GlobalOutboundEdiHeader
from database.models.control_plane import OutboundRoute as GlobalOutboundRoute
from database.models.control_plane import SFTPPartner as GlobalSFTPPartner
from database.models.data_plane import AS2Partner as TenantAS2Partner
from database.models.data_plane import AS2Partnership as TenantAS2Partnership
from database.models.data_plane import InboundRoute as TenantInboundRoute
from database.models.data_plane import OutboundEdiHeader as TenantOutboundEdiHeader
from database.models.data_plane import OutboundRoute as TenantOutboundRoute
from database.models.data_plane import SFTPPartner as TenantSFTPPartner
from database.models.data_plane import Webhook as TenantWebhook
from platform_orm.models import Webhook as GlobalWebhook

from worker.core.replication_graph import EntityDependency, EntitySpec

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
        include_shared=True,
        dependencies=[],
    ),
    "sftp_partner": EntitySpec(
        global_model=GlobalSFTPPartner,
        tenant_model=TenantSFTPPartner,
        include_shared=False,
        dependencies=[],
    ),
    "webhook": EntitySpec(
        global_model=GlobalWebhook,
        tenant_model=TenantWebhook,
        include_shared=False,
        dependencies=[],
    ),
    "outbound_edi_header": EntitySpec(
        global_model=GlobalOutboundEdiHeader,
        tenant_model=TenantOutboundEdiHeader,
        include_shared=False,
        dependencies=[],
    ),
    # ---- Entities with FK dependencies (layer 1) ----
    "as2_partnership": EntitySpec(
        global_model=GlobalAS2Partnership,
        tenant_model=TenantAS2Partnership,
        include_shared=True,
        # FK: local_partner_id → as2_partners.id
        #     remote_partner_id → as2_partners.id
        # Both must be satisfied before the partnership can be inserted.
        dependencies=[
            EntityDependency(
                fk_attr="local_partner_id",
                global_model=GlobalAS2Partner,
                tenant_model=TenantAS2Partner,
                include_shared=True,
            ),
            EntityDependency(
                fk_attr="remote_partner_id",
                global_model=GlobalAS2Partner,
                tenant_model=TenantAS2Partner,
                include_shared=True,
            ),
        ],
    ),
    "inbound_route": EntitySpec(
        global_model=GlobalInboundRoute,
        tenant_model=TenantInboundRoute,
        include_shared=False,
        # CHECK constraint: exactly ONE of these three FK columns is non-null.
        # All three are listed; the driver skips null values automatically.
        # FK: as2_partner_id → as2_partners.id
        #     sftp_partner_id → sftp_partners.id
        #     webhook_id      → webhooks.id
        dependencies=[
            EntityDependency(
                fk_attr="as2_partner_id",
                global_model=GlobalAS2Partner,
                tenant_model=TenantAS2Partner,
                include_shared=True,
            ),
            EntityDependency(
                fk_attr="sftp_partner_id",
                global_model=GlobalSFTPPartner,
                tenant_model=TenantSFTPPartner,
                include_shared=False,
            ),
            EntityDependency(
                fk_attr="webhook_id",
                global_model=GlobalWebhook,
                tenant_model=TenantWebhook,
                include_shared=False,
            ),
        ],
    ),
    "outbound_route": EntitySpec(
        global_model=GlobalOutboundRoute,
        tenant_model=TenantOutboundRoute,
        include_shared=False,
        # CHECK constraint: exactly ONE of these two FK columns is non-null.
        # FK: as2_partner_id  → as2_partners.id
        #     sftp_partner_id → sftp_partners.id
        dependencies=[
            EntityDependency(
                fk_attr="as2_partner_id",
                global_model=GlobalAS2Partner,
                tenant_model=TenantAS2Partner,
                include_shared=True,
            ),
            EntityDependency(
                fk_attr="sftp_partner_id",
                global_model=GlobalSFTPPartner,
                tenant_model=TenantSFTPPartner,
                include_shared=False,
            ),
        ],
    ),
}
