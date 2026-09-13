from datetime import UTC, datetime

from edi.adapters.outbound.database.models.control_plane import OutboundRoute
from edi.adapters.outbound.database.outbound_route_repository import (
    SqlAlchemyOutboundRouteRepository,
)


def test_domain_mapping_uses_defaults_for_presentation_only_fields() -> None:
    timestamp = datetime.now(UTC)
    record = OutboundRoute(
        id="route-1",
        tenant_id="tenant-1",
        trading_partner_id="partner-1",
        name="Primary route",
        active=True,
        created_at=timestamp,
        updated_at=timestamp,
        connection_type="AS2",
        as2_partner_id="as2-1",
        sftp_partner_id=None,
    )

    route = SqlAlchemyOutboundRouteRepository._to_domain_model(record)

    assert route.direction == "OUTBOUND"
    assert route.destination_name is None
    assert route.as2_partner_id == "as2-1"
