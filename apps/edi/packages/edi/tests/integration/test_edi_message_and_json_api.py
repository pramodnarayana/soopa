import pytest
from httpx import AsyncClient
from seedwork import generate_id

from edi.adapters.outbound.database.uow_adapter import (
    SqlAlchemyDataPlaneUnitOfWork as DataPlaneUnitOfWorkPort,
)
from edi.domain.enums import ConnectionType, EdiDirection, MessageStatus
from edi.ports.outbound.transaction_repository import (
    CreateApiGatewayCommand,
    CreateEdiJsonCommand,
    CreateEdiMessageCommand,
)
from edi.testing.fakes.pipeline_fakes import InMemoryStorageAdapter

pytestmark = pytest.mark.asyncio


async def test_edi_json_submission_and_thread(client: AsyncClient):
    """
    Tests submitting an outbound EDI JSON message via POST /api/v1/edi_json,
    and verifying that it can be queried via the transactions thread endpoint
    and the explorer endpoint against a live PostgreSQL instance.
    """
    po_num = f"PO-{generate_id('id')[:8]}"
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
        f"/api/v1/tenants/1/edi/transactions/json?key=po_number&value={po_num}"
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
    client: AsyncClient,
    tenant_db_session,
):
    """
    Tests the creation of EdiMessage, EdiJson, and ApiGateway records for a trace_id,
    and verifying that they appear in the transaction listing, transaction detail,
    and EDI messages explorer endpoints against a live PostgreSQL instance.

    Uses the tenant_db_session fixture which is bound to a rolled-back outer transaction
    (join_transaction_mode="create_savepoint"), guaranteeing no physical writes to the DB.
    """
    tenant_id = "1"
    trace_id = generate_id("id")
    sender_id = f"SENDER_{generate_id('id')[:6]}"
    receiver_id = f"RECV_{generate_id('id')[:6]}"
    msg_id_val = f"MSG_{generate_id('id')[:6]}"

    # 1. Insert records using the fixture session (SAVEPOINT-safe — no physical commit).
    uow = DataPlaneUnitOfWorkPort(
        tenant_session=tenant_db_session, storage=InMemoryStorageAdapter()
    )
    async with uow:
        await uow.transactions.create_edi_message(
            command=CreateEdiMessageCommand(
                trace_id=trace_id,
                tenant_id=tenant_id,
                direction=EdiDirection.INBOUND,
                connection_type=ConnectionType.AS2,
                sender_id=sender_id,
                receiver_id=receiver_id,
                message_id=msg_id_val,
                transaction_type="850",
                format_standard="X12",
                edi_data="ISA*00*...~GS*PO*...~ST*850*0001~SE*1*0001~GE*1*1~IEA*1*1~",
                status=MessageStatus.RECEIVED,
            )
        )
        await uow.transactions.create_edi_json(
            command=CreateEdiJsonCommand(
                trace_id=trace_id,
                tenant_id=tenant_id,
                direction=EdiDirection.INBOUND,
                sender_id=sender_id,
                receiver_id=receiver_id,
                transaction_type="850",
                payload={"po_number": "PO-999"},
                status=MessageStatus.TRANSFORMED,
            )
        )
        await uow.transactions.create_api_gateway(
            command=CreateApiGatewayCommand(
                trace_id=trace_id,
                tenant_id=tenant_id,
                direction=EdiDirection.INBOUND,
                http_status_code=200,
                payload={"po_number": "PO-999"},
                status=MessageStatus.SUCCESS,
            )
        )
        # flush() makes data visible to the same DB connection without a physical commit.
        # The outer transaction.rollback() in the db_connection fixture ensures nothing
        # is persisted to the database after the test.
        await uow.session.flush()

    # 2. List transactions via GET /api/v1/transactions/messages
    res_list = await client.get("/api/v1/tenants/1/edi/transactions/messages")
    assert res_list.status_code == 200, f"Failed to list transactions: {res_list.text}"
    tx_list = res_list.json()["items"]
    assert any(tx["trace_id"] == str(trace_id) for tx in tx_list)

    # 3. Get transaction detail via GET /api/v1/transactions/{trace_id}
    res_detail = await client.get(f"/api/v1/tenants/1/edi/transactions/{trace_id}")
    assert res_detail.status_code == 200, f"Failed to get transaction detail: {res_detail.text}"
    detail = res_detail.json()
    assert detail["edi_message"]["trace_id"] == str(trace_id)
    assert detail["edi_message"]["sender_id"] == sender_id
    assert len(detail["edi_jsons"]) == 1
    assert detail["edi_jsons"][0]["transaction_type"] == "850"
    assert detail["edi_jsons"][0]["status"] == MessageStatus.TRANSFORMED
    assert len(detail["api_gateways"]) == 1
    assert detail["api_gateways"][0]["http_status_code"] == 200
    assert detail["api_gateways"][0]["status"] == MessageStatus.SUCCESS

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
