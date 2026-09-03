import pytest
from datetime import UTC, datetime
from httpx import AsyncClient
from seedwork.utils import generate_id
from sqlalchemy.ext.asyncio import AsyncSession
from edi.domain.models.transactions import EdiMessageDomainModel
from edi.domain.models.base import Direction, RecordStatus


@pytest.mark.asyncio
async def test_list_transactions(client: AsyncClient, db_session: AsyncSession, tenant_db_session: AsyncSession):
    # Insert a dummy message via ORM
    tenant_id = "1"
    trace_id = generate_id("trace")
    
    msg = EdiMessageDomainModel(
        id=generate_id("msg"),
        tenant_id=tenant_id,
        trace_id=trace_id,
        direction=Direction.INBOUND,
        status=RecordStatus.SUCCESS,
        connection_type="AS2",
    )
    
    # We use the tenant_db_session to persist the model manually since it's a tenant data plane record
    from edi.adapters.outbound.database.models.data_plane import EdiMessage
    db_msg = EdiMessage(
        id=msg.id,
        tenant_id=msg.tenant_id,
        trace_id=msg.trace_id,
        direction=msg.direction.value,
        status=msg.status.value,
        edi_data="test_data",
        connection_type=msg.connection_type,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    tenant_db_session.add(db_msg)
    await tenant_db_session.flush()

    response = await client.get("/api/v1/tenants/1/edi/transactions/messages")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) >= 1
    # Check our inserted trace_id is returned
    found = any(i["trace_id"] == trace_id for i in data["items"])
    assert found


@pytest.mark.asyncio
async def test_get_transaction_trace(client: AsyncClient, tenant_db_session: AsyncSession):
    tenant_id = "1"
    trace_id = generate_id("trace")
    
    from edi.adapters.outbound.database.models.data_plane import EdiMessage
    db_msg = EdiMessage(
        id=generate_id("msg"),
        tenant_id=tenant_id,
        trace_id=trace_id,
        direction=Direction.INBOUND.value,
        status=RecordStatus.SUCCESS.value,
        edi_data="test_data",
        connection_type="AS2",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    tenant_db_session.add(db_msg)
    await tenant_db_session.flush()

    response = await client.get(f"/api/v1/tenants/1/edi/transactions/{trace_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["edi_message"]["trace_id"] == trace_id


@pytest.mark.asyncio
async def test_get_transaction_trace_not_found(client: AsyncClient):
    response = await client.get("/api/v1/tenants/1/edi/transactions/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_transaction_json(client: AsyncClient, tenant_db_session: AsyncSession):
    tenant_id = "1"
    trace_id = generate_id("trace")
    
    from edi.adapters.outbound.database.models.data_plane import EdiJson
    db_json = EdiJson(
        id=generate_id("json"),
        tenant_id=tenant_id,
        trace_id=trace_id,
        transaction_type="850",
        direction=Direction.INBOUND.value,
        payload='{"doc": "val"}',
        status=RecordStatus.SUCCESS.value,
        business_metadata={"invoice_id": "INV-123"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    tenant_db_session.add(db_json)
    await tenant_db_session.flush()

    response = await client.get(
        "/api/v1/tenants/1/edi/transactions/json?key=invoice_id&value=INV-123"
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) >= 1
    found = any(i["trace_id"] == trace_id for i in data["items"])
    assert found


@pytest.mark.asyncio
async def test_replay_transaction(client: AsyncClient, tenant_db_session: AsyncSession):
    tenant_id = "1"
    trace_id = generate_id("trace")
    
    from edi.adapters.outbound.database.models.data_plane import EdiMessage
    db_msg = EdiMessage(
        id=generate_id("msg"),
        tenant_id=tenant_id,
        trace_id=trace_id,
        direction=Direction.INBOUND.value,
        status=RecordStatus.SUCCESS.value,
        edi_data="test_data",
        connection_type="AS2",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    tenant_db_session.add(db_msg)
    await tenant_db_session.flush()

    response = await client.post(
        f"/api/v1/tenants/1/edi/transactions/{trace_id}/replay",
        json={"tier": "translation"},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_bulk_replay_transactions(client: AsyncClient, tenant_db_session: AsyncSession):
    tenant_id = "1"
    trace_id_1 = generate_id("trace1")
    trace_id_2 = generate_id("trace2")
    
    from edi.adapters.outbound.database.models.data_plane import EdiMessage
    tenant_db_session.add(EdiMessage(
        id=generate_id("msg"),
        tenant_id=tenant_id,
        trace_id=trace_id_1,
        direction=Direction.INBOUND.value,
        status=RecordStatus.SUCCESS.value,
        edi_data="test_data",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    ))
    tenant_db_session.add(EdiMessage(
        id=generate_id("msg"),
        tenant_id=tenant_id,
        trace_id=trace_id_2,
        direction=Direction.INBOUND.value,
        status=RecordStatus.SUCCESS.value,
        edi_data="test_data",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    ))
    await tenant_db_session.flush()

    response = await client.post(
        "/api/v1/tenants/1/edi/transactions/bulk-replay",
        json={"trace_ids": [trace_id_1, trace_id_2], "tier": "translation"},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    assert response.json()["processed_count"] == 2
