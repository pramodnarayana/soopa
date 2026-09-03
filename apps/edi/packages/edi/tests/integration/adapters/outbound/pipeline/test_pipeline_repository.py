import pytest
from seedwork import generate_id
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.models.data_plane import (
    AS2Partner,
    AS2Partnership,
)
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox as Outbox
from edi.adapters.outbound.pipeline.repository import SqlAlchemyRepositoryAdapter
from edi.config.settings import AppSettings
from edi.domain.constants import EdiIdPrefix
from edi.domain.enums import ConnectionType, EdiDirection, MessageStatus
from edi.testing.fakes.pipeline_fakes import InMemoryStorageAdapter

pytestmark = pytest.mark.asyncio


def make_adapter(session: AsyncSession) -> SqlAlchemyRepositoryAdapter:
    settings = AppSettings.model_construct()
    settings.storage_backend = "local"
    storage = InMemoryStorageAdapter()
    return SqlAlchemyRepositoryAdapter(session, settings, storage)


async def test_save_and_get_edi_message_success(tenant_db_session: AsyncSession) -> None:

    await tenant_db_session.execute(text("SET LOCAL app.current_tenant = 'tenant_1';"))
    adapter = make_adapter(tenant_db_session)
    trace_id = generate_id("sys_trc")

    await adapter.save_edi_message(
        trace_id=trace_id,
        direction=EdiDirection.INBOUND,
        edi_data="ISA*00*...",
        format_standard="X12",
        transaction_type="850",
        status=MessageStatus.RECEIVED,
        connection_type=ConnectionType.AS2,
        sender_id="SENDER_X",
        receiver_id="RECEIVER_X",
        trading_partner_id="PARTNER_X",
        tenant_id="tenant_1",
    )

    # Get the message back
    result = await adapter.get_edi_message(trace_id)

    assert result is not None
    assert result.trace_id == trace_id
    assert result.edi_data == "ISA*00*..."
    assert result.format_standard == "X12"
    assert result.status == MessageStatus.RECEIVED


async def test_update_edi_message_status(tenant_db_session: AsyncSession) -> None:

    await tenant_db_session.execute(text("SET LOCAL app.current_tenant = 'tenant_1';"))
    adapter = make_adapter(tenant_db_session)
    trace_id = generate_id("sys_trc")

    await adapter.save_edi_message(
        trace_id=trace_id,
        direction=EdiDirection.INBOUND,
        edi_data="ISA*00*...",
        format_standard="X12",
        transaction_type="850",
        status=MessageStatus.RECEIVED,
        tenant_id="tenant_1",
    )

    await adapter.update_edi_message_status(trace_id, MessageStatus.TRANSFORMED)

    result = await adapter.get_edi_message(trace_id)
    assert result is not None
    assert result.status == MessageStatus.TRANSFORMED


async def test_save_and_get_api_payload(tenant_db_session: AsyncSession) -> None:

    await tenant_db_session.execute(text("SET LOCAL app.current_tenant = 'tenant_1';"))
    adapter = make_adapter(tenant_db_session)
    trace_id = generate_id("sys_trc")

    # Needs to be saved using adapter
    await adapter.save_api_payload(
        trace_id=trace_id,
        direction=EdiDirection.OUTBOUND,
        payload={"data": "foo"},
        status=MessageStatus.PENDING_DELIVERY,
    )

    result = await adapter.get_api_payload(trace_id)

    assert result is not None
    assert result["status"] == MessageStatus.PENDING_DELIVERY
    assert result["payload"] == {"data": "foo"}


async def test_publish_outbox_event(tenant_db_session: AsyncSession) -> None:

    await tenant_db_session.execute(text("SET LOCAL app.current_tenant = 'tenant_1';"))
    adapter = make_adapter(tenant_db_session)
    idempotency_key = generate_id("sys_idp")

    await adapter.publish_outbox_event(idempotency_key, "DELIVER", {"trace_id": "123"})

    # Query to verify it was inserted
    stmt = select(Outbox).where(Outbox.idempotency_key == idempotency_key)
    result = (await tenant_db_session.execute(stmt)).scalar_one_or_none()

    assert result is not None
    assert result.event_type == "DELIVER"
    assert result.payload == {"trace_id": "123"}


async def test_update_api_payload_status(tenant_db_session: AsyncSession) -> None:

    await tenant_db_session.execute(text("SET LOCAL app.current_tenant = 'tenant_1';"))
    adapter = make_adapter(tenant_db_session)
    trace_id = generate_id("sys_trc")

    await adapter.save_api_payload(
        trace_id=trace_id,
        direction=EdiDirection.OUTBOUND,
        payload={"data": "foo"},
        status=MessageStatus.PENDING_DELIVERY,
    )

    await adapter.update_api_payload_status(trace_id, MessageStatus.DELIVERED)

    result = await adapter.get_api_payload(trace_id)
    assert result is not None
    assert result["status"] == MessageStatus.DELIVERED


async def test_get_as2_partner_inactive_raises(tenant_db_session: AsyncSession) -> None:

    await tenant_db_session.execute(text("SET LOCAL app.current_tenant = 'tenant_1';"))
    adapter = make_adapter(tenant_db_session)

    partner_id = generate_id(EdiIdPrefix.AS2_PARTNER)
    partner = AS2Partner(
        id=partner_id,
        name="Test Partner",
        as2_id="TEST_AS2",
        active=False,
    )
    tenant_db_session.add(partner)

    partnership = AS2Partnership(
        id=generate_id("edi_as2_pship"),
        name="Test Partnership",
        local_partner_id=partner_id,
        remote_partner_id=partner_id,
        active=True,
    )
    tenant_db_session.add(partnership)
    await tenant_db_session.flush()

    with pytest.raises(ValueError, match="exists but is inactive"):
        await adapter.get_as2_partner(partner_id)


async def test_get_as2_partnership_inactive_raises(tenant_db_session: AsyncSession) -> None:

    await tenant_db_session.execute(text("SET LOCAL app.current_tenant = 'tenant_1';"))
    adapter = make_adapter(tenant_db_session)

    partner_id = generate_id(EdiIdPrefix.AS2_PARTNER)
    partner = AS2Partner(
        id=partner_id,
        name="Test Partner",
        as2_id="TEST_AS2",
        active=True,
    )
    tenant_db_session.add(partner)

    partnership = AS2Partnership(
        id=generate_id("edi_as2_pship"),
        name="Test Partnership",
        local_partner_id=partner_id,
        remote_partner_id=partner_id,
        active=False,
    )
    tenant_db_session.add(partnership)
    await tenant_db_session.flush()

    with pytest.raises(ValueError, match="exists but is inactive"):
        await adapter.get_as2_partner(partner_id)


async def test_get_local_as2_partner_inactive_raises(tenant_db_session: AsyncSession) -> None:

    await tenant_db_session.execute(text("SET LOCAL app.current_tenant = 'tenant_1';"))
    adapter = make_adapter(tenant_db_session)

    partner_id = generate_id(EdiIdPrefix.AS2_PARTNER)
    partner = AS2Partner(
        id=partner_id,
        name="Test Partner",
        as2_id="TEST_AS2",
        active=False,
    )
    tenant_db_session.add(partner)
    await tenant_db_session.flush()

    with pytest.raises(ValueError, match="Local AS2 Partner"):
        await adapter.get_local_as2_partner(partner_id)
