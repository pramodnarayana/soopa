"""
Replication Registry — Infrastructure Wiring of the Dependency Graph.

This module is the SINGLE SOURCE OF TRUTH for which entities are replicated
and what their FK dependencies are. It wires concrete SQLAlchemy model classes
into the EntitySpec declarative structure defined in edi.domain.replication.
"""

from database.models import Webhook
from edi.adapters.outbound.database.models import control_plane, data_plane
from edi.adapters.outbound.database.replication_mappers import (
    map_as2_partner,
    map_as2_partnership,
    map_inbound_route,
    map_outbound_edi_header,
    map_outbound_route,
    map_sftp_partner,
    map_webhook,
)
from edi.domain.replication import (
    EntityDependency,
    EntitySpec,
    validate_replication_graph,
)

# ---------------------------------------------------------------------------
# Replication Graph
#
# Entities are declared without regard for order here — the topological_layers
# algorithm in edi.domain.replication derives the correct insertion order at
# runtime from the declared dependencies.
# ---------------------------------------------------------------------------
REPLICATION_GRAPH: dict[str, EntitySpec] = {
    # ---- Leaf entities (no FK dependencies) ----
    "as2_partner": EntitySpec(
        control_plane_model=control_plane.AS2Partner,
        data_plane_model=data_plane.AS2Partner,
        mapper=map_as2_partner,
        include_shared=True,
        dependencies=[],
    ),
    "sftp_partner": EntitySpec(
        control_plane_model=control_plane.SFTPPartner,
        data_plane_model=data_plane.SFTPPartner,
        mapper=map_sftp_partner,
        include_shared=False,
        dependencies=[],
    ),
    "webhook": EntitySpec(
        control_plane_model=Webhook,
        data_plane_model=data_plane.Webhook,
        mapper=map_webhook,
        include_shared=False,
        dependencies=[],
    ),
    "outbound_edi_header": EntitySpec(
        control_plane_model=control_plane.OutboundEdiHeader,
        data_plane_model=data_plane.OutboundEdiHeader,
        mapper=map_outbound_edi_header,
        include_shared=False,
        dependencies=[],
    ),
    # ---- Entities with FK dependencies (layer 1) ----
    "as2_partnership": EntitySpec(
        control_plane_model=control_plane.AS2Partnership,
        data_plane_model=data_plane.AS2Partnership,
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
        control_plane_model=control_plane.InboundRoute,
        data_plane_model=data_plane.InboundRoute,
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
        control_plane_model=control_plane.OutboundRoute,
        data_plane_model=data_plane.OutboundRoute,
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
