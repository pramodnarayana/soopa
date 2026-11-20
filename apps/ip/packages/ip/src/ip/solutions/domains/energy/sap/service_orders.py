"""SAP IS-U service order mutation connector endpoint."""

from __future__ import annotations

from ip.sdk import MutationSpec, RequestBuilder, RequestSpec
from ip.solutions.domains.energy.building_blocks.protocol_headers import build_sap_odata_headers
from ip.solutions.domains.energy.sap.commands import CreateServiceOrderCommand


def create_sap_service_order(cmd: CreateServiceOrderCommand) -> RequestSpec:
    """Builds a standard HTTP POST mutation for SAP IS-U ServiceOrders."""
    return (
        RequestBuilder.post("/sap/opu/odata/sap/ERP_UTILITIES_UMC/ServiceOrders")
        .with_headers(build_sap_odata_headers())
        .with_body(
            {
                "OrderType": cmd.order_type,
                "ServicePoint": cmd.service_point_id,
                "DeviceID": cmd.meter_serial_number,
                "Description": cmd.reason,
                "ScheduledDate": cmd.scheduled_date,
            }
        )
        .build()
    )


SAP_SERVICE_ORDERS_MUTATION = MutationSpec(
    app="sap_is_u",
    entity="service_orders",
    operation="CREATE",
    fn=create_sap_service_order,
    description="Builds OData POST mutation to create service orders in SAP IS-U.",
)

__all__ = [
    "SAP_SERVICE_ORDERS_MUTATION",
    "create_sap_service_order",
]
