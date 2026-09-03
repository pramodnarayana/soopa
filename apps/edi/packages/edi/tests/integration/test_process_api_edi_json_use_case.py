import json

import pytest
import pytest_asyncio
from identity.domain.constants import IdentityIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from edi.adapters.outbound.database.uow_adapter import SqlAlchemyDataPlaneUnitOfWork
from edi.application.dtos.commands import ProcessApiEdiJsonCommand
from edi.application.use_cases.process_api_edi_json_use_case import ProcessApiEdiJsonUseCase
from edi.domain.constants import EdiIdPrefix
from edi.testing.fakes.pipeline_fakes import InMemoryStorageAdapter


@pytest_asyncio.fixture
async def tenant_session(tenant_db_connection):
    SessionLocal = async_sessionmaker(
        bind=tenant_db_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        info={"session_type": "tenant"},
        join_transaction_mode="create_savepoint",
    )
    async with SessionLocal() as session:
        yield session


@pytest.mark.asyncio
async def test_process_api_edi_json_success(tenant_session):
    uow = SqlAlchemyDataPlaneUnitOfWork(tenant_session, InMemoryStorageAdapter())
    svc = ProcessApiEdiJsonUseCase(uow)

    tenant_id = generate_id(IdentityIdPrefix.TENANT)
    trace_id = await svc.process_api_edi_json(
        ProcessApiEdiJsonCommand(
            tenant_id=tenant_id,
            trading_partner_id=generate_id(EdiIdPrefix.AS2_PARTNER),
            payload={"transaction_type": "204", "shipment_id": "SHP001"},
        )
    )

    assert trace_id is not None

    # Verify db state
    result = await tenant_session.execute(
        text("SELECT transaction_type, payload FROM edi_json WHERE trace_id = :trace_id"),
        {"trace_id": trace_id},
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "204"
    assert row[1]["transaction_type"] == "204"

    # Verify outbox event
    outbox_result = await tenant_session.execute(
        text(
            "SELECT event_type, payload FROM outbox WHERE event_type = 'TRANSFORM_EVENT' AND payload->>'trace_id' = :trace_id"
        ),
        {"trace_id": trace_id},
    )
    outbox_row = outbox_result.fetchone()
    assert outbox_row is not None
    assert outbox_row[0] == "TRANSFORM_EVENT"

    outbox_payload = outbox_row[1]
    if isinstance(outbox_payload, str):
        outbox_payload = json.loads(outbox_payload)
    assert outbox_payload["trace_id"] == trace_id


@pytest.mark.asyncio
async def test_process_api_edi_json_heading(tenant_session):
    uow = SqlAlchemyDataPlaneUnitOfWork(tenant_session, InMemoryStorageAdapter())
    svc = ProcessApiEdiJsonUseCase(uow)

    trace_id = await svc.process_api_edi_json(
        ProcessApiEdiJsonCommand(
            tenant_id=generate_id(IdentityIdPrefix.TENANT),
            trading_partner_id=generate_id(EdiIdPrefix.AS2_PARTNER),
            payload=[
                {
                    "heading": {
                        "transaction_set_header_ST": {"transaction_set_identifier_code": "850"}
                    }
                }
            ],
        )
    )
    assert trace_id is not None

    result = await tenant_session.execute(
        text("SELECT transaction_type FROM edi_json WHERE trace_id = :trace_id"),
        {"trace_id": trace_id},
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "850"


@pytest.mark.asyncio
async def test_process_api_edi_json_st_segment(tenant_session):
    uow = SqlAlchemyDataPlaneUnitOfWork(tenant_session, InMemoryStorageAdapter())
    svc = ProcessApiEdiJsonUseCase(uow)

    trace_id = await svc.process_api_edi_json(
        ProcessApiEdiJsonCommand(
            tenant_id=generate_id(IdentityIdPrefix.TENANT),
            trading_partner_id=generate_id(EdiIdPrefix.AS2_PARTNER),
            payload=[{"ST": {"ST01": "855"}}],
        )
    )
    assert trace_id is not None

    result = await tenant_session.execute(
        text("SELECT transaction_type FROM edi_json WHERE trace_id = :trace_id"),
        {"trace_id": trace_id},
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "855"


@pytest.mark.asyncio
async def test_process_api_edi_json_list_extraction(tenant_session):
    uow = SqlAlchemyDataPlaneUnitOfWork(tenant_session, InMemoryStorageAdapter())
    svc = ProcessApiEdiJsonUseCase(uow)

    payload = [
        {"ST": {"ST01": "850"}, "BEG": {"BEG03": "123"}, "foo": "bar"},
        {"ST": {"ST01": "850"}, "BEG": {"BEG03": "456"}, "foo": "baz"},
    ]
    p_id = generate_id(EdiIdPrefix.AS2_PARTNER)
    trace_id = await svc.process_api_edi_json(
        ProcessApiEdiJsonCommand(
            tenant_id=generate_id(IdentityIdPrefix.TENANT), trading_partner_id=p_id, payload=payload
        )
    )
    assert trace_id is not None

    result = await tenant_session.execute(
        text("SELECT business_metadata FROM edi_json WHERE trace_id = :trace_id"),
        {"trace_id": trace_id},
    )
    row = result.fetchone()
    assert row is not None

    business_metadata = row[0]
    if isinstance(business_metadata, str):
        business_metadata = json.loads(business_metadata)

    assert business_metadata == {
        "po_number": ["123", "456"],
        "business_reference": ["123", "456"],
        "_routing": {"trading_partner_id": p_id},
    }
