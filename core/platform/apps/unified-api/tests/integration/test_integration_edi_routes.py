import json

import httpx
import pytest
from fastapi import FastAPI
from seedwork.events import EventEnvelope

from unified_api.adapters.inbound.http.dependencies.edi.services import get_outbox_publisher

pytestmark = pytest.mark.integration


class _InMemoryOutboxPublisher:
    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []

    async def publish(self, event: EventEnvelope) -> None:
        self.published.append(event)


@pytest.mark.asyncio
async def test_get_trading_partners(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]
    response = await auth_client.get(f"/api/v1/tenants/{tenant_id}/edi/trading-partners")
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_get_trading_partner_by_id(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]
    response = await auth_client.get(f"/api/v1/tenants/{tenant_id}/edi/trading-partners/tp_123")
    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_get_transactions(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]
    response = await auth_client.get(f"/api/v1/tenants/{tenant_id}/edi/transactions/messages")
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_edi_headers_inbound_and_outbound_routes_crud(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    # Seed a tenant SFTP partner for route binding
    sftp_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/edi/trading-partners/sftp",
        json={
            "name": "Route Target SFTP",
            "host": "sftp-route.example.com",
            "port": 22,
            "username": "ediuser",
            "password": "sftp-secret-password",
            "inbound_remote_path": "/in",
            "outbound_remote_path": "/out",
        },
    )
    assert sftp_res.status_code == 201, sftp_res.text
    sftp_partner_id = sftp_res.json()["partner_id"]

    # 1. EDI Headers CRUD
    headers_url = f"/api/v1/tenants/{tenant_id}/edi/edi-headers"
    create_hdr = await auth_client.post(
        headers_url,
        json={
            "name": "Acme 850 Header",
            "trading_partner_id": "ACME_ERP_01",
            "isa_sender_id": "SOOPAISA",
            "isa_sender_qualifier": "ZZ",
            "isa_receiver_id": "ACMEISA",
            "isa_receiver_qualifier": "ZZ",
            "gs_sender_id": "SOOPAGS",
            "gs_receiver_id": "ACMEGS",
            "transaction_type": "850",
            "default_standard": "x12",
            "default_version": "004010",
        },
    )
    assert create_hdr.status_code == 201, create_hdr.text
    header_id = create_hdr.json()["id"]

    list_hdr = await auth_client.get(headers_url)
    assert list_hdr.status_code == 200
    assert any(h["id"] == header_id for h in list_hdr.json())

    patch_hdr = await auth_client.patch(
        f"{headers_url}/{header_id}",
        json={"name": "Acme 850 Header Updated"},
    )
    assert patch_hdr.status_code == 200
    assert patch_hdr.json() == {"status": "ok"}
    updated_headers = (await auth_client.get(headers_url)).json()
    updated_hdr = next(h for h in updated_headers if h["id"] == header_id)
    assert updated_hdr["name"] == "Acme 850 Header Updated"

    del_hdr = await auth_client.delete(f"{headers_url}/{header_id}")
    assert del_hdr.status_code == 204

    del_hdr_missing = await auth_client.delete(f"{headers_url}/hdr_nonexistent")
    assert del_hdr_missing.status_code == 404

    # 2. Inbound Routes CRUD
    in_url = f"/api/v1/tenants/{tenant_id}/edi/inbound-routes"
    create_in = await auth_client.post(
        in_url,
        json={
            "name": "Inbound 850 SFTP Bridge",
            "trading_partner_id": "ACME_ERP_01",
            "isa_sender_id": "ACMEISA",
            "isa_receiver_id": "SOOPAISA",
            "gs_sender_id": "ACMEGS",
            "gs_receiver_id": "SOOPAGS",
            "transaction_type": "850",
            "processing_mode": "PASSTHROUGH",
            "sftp_partner_id": sftp_partner_id,
        },
    )
    assert create_in.status_code == 201, create_in.text
    in_route_id = create_in.json()["route_id"]

    list_in = await auth_client.get(in_url)
    assert list_in.status_code == 200
    assert any(r["route_id"] == in_route_id for r in list_in.json())

    patch_in = await auth_client.patch(
        f"{in_url}/{in_route_id}",
        json={"name": "Inbound 850 Updated", "active": False},
    )
    assert patch_in.status_code == 200
    assert patch_in.json() == {"status": "ok"}
    updated_in_routes = (await auth_client.get(in_url)).json()
    updated_in = next(r for r in updated_in_routes if r["route_id"] == in_route_id)
    assert updated_in["name"] == "Inbound 850 Updated"
    assert updated_in["active"] is False

    del_in = await auth_client.delete(f"{in_url}/{in_route_id}")
    assert del_in.status_code == 204

    del_in_missing = await auth_client.delete(f"{in_url}/rt_nonexistent")
    assert del_in_missing.status_code == 404

    # 3. Outbound Routes CRUD + destination validation
    out_url = f"/api/v1/tenants/{tenant_id}/edi/outbound-routes"
    invalid_out = await auth_client.post(
        out_url,
        json={
            "name": "Missing Destination",
            "trading_partner_id": "ACME_ERP_01",
        },
    )
    assert invalid_out.status_code == 422

    create_out = await auth_client.post(
        out_url,
        json={
            "name": "Outbound SFTP Route",
            "trading_partner_id": "ACME_ERP_01",
            "sftp_partner_id": sftp_partner_id,
        },
    )
    assert create_out.status_code == 201, create_out.text
    out_route_id = create_out.json()["route_id"]

    list_out = await auth_client.get(out_url)
    assert list_out.status_code == 200
    assert any(r["route_id"] == out_route_id for r in list_out.json())

    patch_out = await auth_client.patch(
        f"{out_url}/{out_route_id}",
        json={"name": "Outbound SFTP Route Updated", "active": False},
    )
    assert patch_out.status_code == 200
    assert patch_out.json() == {"status": "ok"}
    updated_out_routes = (await auth_client.get(out_url)).json()
    updated_out = next(r for r in updated_out_routes if r["route_id"] == out_route_id)
    assert updated_out["name"] == "Outbound SFTP Route Updated"
    assert updated_out["active"] is False

    del_out = await auth_client.delete(f"{out_url}/{out_route_id}")
    assert del_out.status_code == 204

    del_out_missing = await auth_client.delete(f"{out_url}/rt_nonexistent")
    assert del_out_missing.status_code == 404


@pytest.mark.asyncio
async def test_edi_tools_transform_variants(auth_client: httpx.AsyncClient) -> None:
    sample_x12 = (
        "ISA*00*          *00*          *ZZ*PARTNER        *ZZ*SOOPAEDI       "
        "*260101*1200*U*00401*000000001*0*P*>~"
        "GS*FA*PARTNER*SOOPAEDI*20260101*1200*1*X*004010~"
        "ST*997*0001~"
        "AK1*PO*1~"
        "AK9*A*1*1*1~"
        "SE*4*0001~"
        "GE*1*1~"
        "IEA*1*000000001~"
    )
    edi_to_json_res = await auth_client.post(
        "/api/v1/edi-tools/transform",
        json={"action": "EDI_TO_JSON", "payload": sample_x12},
    )
    assert edi_to_json_res.status_code == 200
    assert edi_to_json_res.json()["valid"] is True
    envelope_str = edi_to_json_res.json()["result"]
    assert envelope_str is not None

    # Round-trip JSON_TO_EDI with envelope {"meta": ..., "data": ...}
    json_to_edi_res = await auth_client.post(
        "/api/v1/edi-tools/transform",
        json={"action": "JSON_TO_EDI", "payload": envelope_str},
    )
    assert json_to_edi_res.status_code == 200
    assert json_to_edi_res.json()["valid"] is True
    assert "ST*997*0001" in json_to_edi_res.json()["result"]

    # Invalid JSON syntax returns structured invalid_json response
    bad_json_res = await auth_client.post(
        "/api/v1/edi-tools/transform",
        json={"action": "JSON_TO_EDI", "payload": "{not-valid-json"},
    )
    assert bad_json_res.status_code == 200
    assert bad_json_res.json()["valid"] is False
    assert "invalid_json" in bad_json_res.json()["error"]

    # Non-dict/list JSON primitive raises 400
    primitive_res = await auth_client.post(
        "/api/v1/edi-tools/transform",
        json={"action": "JSON_TO_EDI", "payload": json.dumps("plain-string")},
    )
    assert primitive_res.status_code == 400

    # List containing non-dict raises 400
    bad_list_res = await auth_client.post(
        "/api/v1/edi-tools/transform",
        json={"action": "JSON_TO_EDI", "payload": json.dumps([123])},
    )
    assert bad_list_res.status_code == 400


@pytest.mark.asyncio
async def test_dashboard_explorer_outbound_submission_and_transactions(
    app: FastAPI,
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    dash_res = await auth_client.get(f"/api/v1/tenants/{tenant_id}/edi/dashboard")
    assert dash_res.status_code == 200
    assert dash_res.json()["status"] == "active"

    edi_sub_app: FastAPI | None = app.state.edi_app
    assert edi_sub_app is not None
    publisher = _InMemoryOutboxPublisher()
    edi_sub_app.dependency_overrides[get_outbox_publisher] = lambda: publisher

    try:
        submit_res = await auth_client.post(
            "/api/v1/edi_json",
            headers={"Idempotency-Key": "idem-edi-json-001"},
            json={
                "trading_partner_id": "ACME_ERP_01",
                "transaction_type": "850",
                "payload": {"po_number": "PO-777", "items": [{"sku": "SKU-1", "qty": 5}]},
            },
        )
        assert submit_res.status_code == 202, submit_res.text
        trace_id = submit_res.json()["trace_id"]
        assert len(publisher.published) >= 1

        # Explorer endpoints
        exp_msgs = await auth_client.post(
            f"/api/v1/tenants/{tenant_id}/edi/explorer/edi-messages",
            json={"filters": [{"field": "direction", "operator": "eq", "value": "OUTBOUND"}]},
        )
        assert exp_msgs.status_code == 200

        exp_json = await auth_client.post(
            f"/api/v1/tenants/{tenant_id}/edi/explorer/edi-json",
            json={"filters": [{"field": "trace_id", "operator": "eq", "value": trace_id}]},
        )
        assert exp_json.status_code == 200
        assert len(exp_json.json()["items"]) == 1

        exp_invalid = await auth_client.post(
            f"/api/v1/tenants/{tenant_id}/edi/explorer/edi-messages",
            json={"filters": [{"field": "disallowed_sql_col", "operator": "eq", "value": "x"}]},
        )
        assert exp_invalid.status_code == 422

        # Transactions endpoints
        json_thread = await auth_client.get(
            f"/api/v1/tenants/{tenant_id}/edi/transactions/json",
            params={"key": "po_number", "value": "PO-777"},
        )
        assert json_thread.status_code == 200

        trace_res = await auth_client.get(
            f"/api/v1/tenants/{tenant_id}/edi/transactions/{trace_id}"
        )
        assert trace_res.status_code == 200
        assert len(trace_res.json()["edi_json"]) == 1

        missing_trace = await auth_client.get(
            f"/api/v1/tenants/{tenant_id}/edi/transactions/trc_nonexistent"
        )
        assert missing_trace.status_code == 404

        lineage_res = await auth_client.get(
            f"/api/v1/tenants/{tenant_id}/edi/transactions/{trace_id}/lineage"
        )
        assert lineage_res.status_code == 200

        replay_missing = await auth_client.post(
            f"/api/v1/tenants/{tenant_id}/edi/transactions/trc_nonexistent/replay",
            json={"checkpoint": "TRANSFORM"},
        )
        assert replay_missing.status_code == 404

        mod_replay_missing = await auth_client.post(
            f"/api/v1/tenants/{tenant_id}/edi/transactions/trc_nonexistent/modify-and-replay",
            json={"modified_payload": "ISA*00*..."},
        )
        assert mod_replay_missing.status_code == 404

        replay_ok = await auth_client.post(
            f"/api/v1/tenants/{tenant_id}/edi/transactions/{trace_id}/replay",
            json={"checkpoint": "TRANSFORM"},
        )
        assert replay_ok.status_code == 202
        replay_body = replay_ok.json()
        assert replay_body["status"] == "accepted"
        assert replay_body["trace_id"] == trace_id
        assert replay_body["replay_trace_id"] != trace_id

        bulk_replay_transform_missing = await auth_client.post(
            f"/api/v1/tenants/{tenant_id}/edi/transactions/bulk-replay",
            json={"trace_ids": [trace_id], "checkpoint": "TRANSFORM"},
        )
        assert bulk_replay_transform_missing.status_code == 404

        bulk_replay_delivery = await auth_client.post(
            f"/api/v1/tenants/{tenant_id}/edi/transactions/bulk-replay",
            json={"trace_ids": [trace_id], "checkpoint": "DELIVERY"},
        )
        assert bulk_replay_delivery.status_code == 404
    finally:
        edi_sub_app.dependency_overrides.pop(get_outbox_publisher, None)
