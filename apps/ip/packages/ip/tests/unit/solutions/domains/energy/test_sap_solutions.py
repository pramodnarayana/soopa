"""Unit tests for SAP IS-U OData building blocks and mutation connector."""

from ip.solutions.domains.energy.building_blocks.protocol_headers import build_sap_odata_headers
from ip.solutions.domains.energy.sap.commands import CreateServiceOrderCommand
from ip.solutions.domains.energy.sap.service_orders import create_sap_service_order
from seedwork.domain.types import JsonDict


def test_build_sap_odata_headers_includes_csrf_token() -> None:
    headers = build_sap_odata_headers(csrf_token="token_abc_123")
    assert headers["Accept"] == "application/json"
    assert headers["Content-Type"] == "application/json"
    assert headers["x-csrf-token"] == "token_abc_123"


def test_create_service_order_command_from_payload_deserializes() -> None:
    payload: JsonDict = {
        "service_point_id": "SP-999",
        "meter_serial_number": "MTR-111",
        "scheduled_date": "2026-11-01",
        "order_type": "PM02",
        "reason": "Meter Replacement",
    }
    cmd = CreateServiceOrderCommand.from_payload(payload)

    assert cmd.service_point_id == "SP-999"
    assert cmd.meter_serial_number == "MTR-111"
    assert cmd.scheduled_date == "2026-11-01"
    assert cmd.order_type == "PM02"
    assert cmd.reason == "Meter Replacement"


def test_create_sap_service_order_constructs_post_request_spec() -> None:
    cmd = CreateServiceOrderCommand(
        service_point_id="SP-100",
        meter_serial_number="MTR-200",
        scheduled_date="2026-12-01",
    )
    spec = create_sap_service_order(cmd)

    assert spec.method == "POST"
    assert spec.path == "/sap/opu/odata/sap/ERP_UTILITIES_UMC/ServiceOrders"
    assert isinstance(spec.body, dict)
    assert spec.body["ServicePoint"] == "SP-100"
    assert spec.body["DeviceID"] == "MTR-200"
    assert spec.body["OrderType"] == "PM01"
