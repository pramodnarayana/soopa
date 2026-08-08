import uuid

import pytest
from httpx import AsyncClient

from edi.adapters.uow_adapter import SqlAlchemyDataPlaneUnitOfWork as DataPlaneUnitOfWork

pytestmark = pytest.mark.asyncio


async def test_edi_json_submission_and_thread(client: AsyncClient):
    """
    Tests submitting an outbound EDI JSON message via POST /api/v1/edi_json,
    and verifying that it can be queried via the transactions thread endpoint
    and the explorer endpoint against a live PostgreSQL instance.
    """
    po_num = f"PO-{str(uuid.uuid4())[:8]}"
    payload = {
        "trading_partner_id": "TP_TEST_WALMART",
        "transaction_type": "850",
        "payload": {
            "transaction_type": "850",
            "BEG": {"BEG03": po_num, "BEG05": "20260725"},
            "items": [{"sku": "ITEM01", "qty": 10}],
        },
    }

    # 1. Submit outbound JSON message
    res_post = await client.post("/api/v1/edi_json", json=payload)
    assert res_post.status_code == 202, f"Failed to submit outbound EDI JSON: {res_post.text}"
    response_data = res_post.json()
    assert response_data["status"] == "ACCEPTED"
    trace_id = response_data["trace_id"]
    assert trace_id is not None

    # 2. Query transaction thread by po_number
    res_thread = await client.get(
        f"/api/v1/tenants/1/edi/transactions/thread?key=po_number&value={po_num}"
    )
    assert res_thread.status_code == 200, f"Failed to get transaction thread: {res_thread.text}"
    thread_items = res_thread.json()["items"]
    assert len(thread_items) >= 1
    assert any(item["trace_id"] == trace_id for item in thread_items)

    # 3. Explore EDI JSON via POST /api/v1/explorer/edi-json
    explore_payload = {
        "filters": [
            {
                "field": "business_metadata.po_number",
                "operator": "eq",
                "value": po_num,
            }
        ]
    }
    res_explore = await client.post("/api/v1/tenants/1/edi/explorer/edi-json", json=explore_payload)
    assert res_explore.status_code == 200, f"Failed to explore EDI JSON: {res_explore.text}"
    explore_items = res_explore.json()["items"]
    assert any(item["trace_id"] == trace_id for item in explore_items)


async def test_edi_message_explorer_and_detail(
    client: AsyncClient, override_get_global_session, override_get_tenant_session
):
    """
    Tests the creation of EdiMessage, EdiJson, and ApiGateway records for a trace_id,
    and verifying that they appear in the transaction listing, transaction detail,
    and EDI messages explorer endpoints against a live PostgreSQL instance.
    """
    # Expose the tenant ID resolved by the authentication fixture
    tenant_id = "1"

    trace_id = str(uuid.uuid4())
    sender_id = f"SENDER_{str(uuid.uuid4())[:6]}"
    receiver_id = f"RECV_{str(uuid.uuid4())[:6]}"
    msg_id_val = f"MSG_{str(uuid.uuid4())[:6]}"

    # 1. Insert records directly using DataPlaneUnitOfWork to simulate completed pipeline
    gs_gen = override_get_global_session()
    ts_gen = override_get_tenant_session(tenant_id)
    await gs_gen.__anext__()
    ts = await ts_gen.__anext__()
    try:
        uow = DataPlaneUnitOfWork(tenant_session=ts)
        async with uow:
            # Create EdiMessage
            await uow.transactions.create_edi_message(
                tenant_id=tenant_id,
                payload={
                    "trace_id": trace_id,
                    "direction": "INBOUND",
                    "connection_type": "AS2",
                    "sender_id": sender_id,
                    "receiver_id": receiver_id,
                    "message_id": msg_id_val,
                    "transaction_type": "850",
                    "format_standard": "X12",
                    "edi_data": "ISA*00*...~GS*PO*...~ST*850*0001~SE*1*0001~GE*1*1~IEA*1*1~",
                    "status": "RECEIVED",
                },
            )
            # Create EdiJson
            await uow.transactions.create_edi_json(
                tenant_id=tenant_id,
                payload={
                    "trace_id": trace_id,
                    "direction": "INBOUND",
                    "sender_id": sender_id,
                    "receiver_id": receiver_id,
                    "transaction_type": "850",
                    "payload": {"po_number": "PO-999"},
                    "status": "TRANSFORMED",
                },
            )
            # Create ApiGateway
            await uow.transactions.create_api_gateway(
                tenant_id=tenant_id,
                payload={
                    "trace_id": trace_id,
                    "direction": "INBOUND",
                    "http_status_code": 200,
                    "payload": {"po_number": "PO-999"},
                    "status": "SUCCESS",
                },
            )
            await uow.commit()
    finally:
        await gs_gen.aclose()
        await ts_gen.aclose()

    # 2. List transactions via GET /api/v1/transactions
    res_list = await client.get("/api/v1/tenants/1/edi/transactions")
    assert res_list.status_code == 200, f"Failed to list transactions: {res_list.text}"
    tx_list = res_list.json()["items"]
    assert any(tx["trace_id"] == str(trace_id) for tx in tx_list)

    # 3. Get transaction detail via GET /api/v1/transactions/{trace_id}
    res_detail = await client.get(f"/api/v1/tenants/1/edi/transactions/{trace_id}")
    assert res_detail.status_code == 200, f"Failed to get transaction detail: {res_detail.text}"
    detail = res_detail.json()
    assert detail["edi_message"]["trace_id"] == str(trace_id)
    assert detail["edi_message"]["sender_id"] == sender_id
    assert len(detail["edi_json"]) == 1
    assert detail["edi_json"][0]["transaction_type"] == "850"
    assert detail["edi_json"][0]["status"] == "TRANSFORMED"
    assert len(detail["api_gateway"]) == 1
    assert detail["api_gateway"][0]["http_status_code"] == 200
    assert detail["api_gateway"][0]["status"] == "SUCCESS"

    # 4. Explore EDI messages via POST /api/v1/explorer/edi-messages
    explore_payload = {
        "filters": [
            {
                "field": "sender_id",
                "operator": "eq",
                "value": sender_id,
            }
        ]
    }
    res_explore = await client.post(
        "/api/v1/tenants/1/edi/explorer/edi-messages", json=explore_payload
    )
    assert res_explore.status_code == 200, f"Failed to explore EDI messages: {res_explore.text}"
    explore_msgs = res_explore.json()["items"]
    assert any(m["trace_id"] == str(trace_id) for m in explore_msgs)
