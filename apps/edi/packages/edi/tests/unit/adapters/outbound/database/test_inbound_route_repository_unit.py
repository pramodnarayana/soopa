from datetime import UTC, datetime

from edi.adapters.outbound.database.control_plane.inbound_route_repository import (
    SqlAlchemyInboundRouteRepository,
)
from edi.adapters.outbound.database.models.control_plane import InboundRoute


def test_domain_mapping_uses_defaults_for_presentation_only_fields() -> None:
    timestamp = datetime.now(UTC)
    record = InboundRoute(
        id="route-1",
        tenant_id="tenant-1",
        name="Primary inbound route",
        isa_sender_id="SENDER1",
        isa_receiver_id="RECEIVER1",
        active=True,
        created_at=timestamp,
        updated_at=timestamp,
        trading_partner_id="partner-1",
        gs_sender_id=None,
        gs_receiver_id=None,
        transaction_type="850",
        processing_mode="TRANSFORM",
        webhook_id="webhook-1",
        as2_partner_id=None,
        sftp_partner_id=None,
        connection_type="API",
    )

    route = SqlAlchemyInboundRouteRepository._to_domain_model(record)

    assert route.direction == "INBOUND"
    assert route.destination_name is None
    assert route.webhook_id == "webhook-1"
