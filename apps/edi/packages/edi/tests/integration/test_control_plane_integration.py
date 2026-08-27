import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.models.control_plane import InboundRoute


@pytest.mark.integration
@pytest.mark.asyncio
async def test_inbound_route_webhook_id_foreign_key_violation(
    db_session: AsyncSession,
) -> None:
    """
    Test that creating an InboundRoute with an unknown webhook_id
    fails with an IntegrityError because of the foreign key constraint
    to ucp.webhooks.id, without needing to resolve the GlobalWebhook model.
    """
    inbound_route = InboundRoute(
        id="route_123",
        tenant_id="tenant_123",
        name="test_route",
        isa_sender_id="SENDER123",
        isa_receiver_id="RECEIVER123",
        transaction_type="850",
        webhook_id="nonexistent_webhook_id",
    )
    db_session.add(inbound_route)

    with pytest.raises(IntegrityError) as exc_info:
        await db_session.commit()

    # Assert that the error is due to the foreign key constraint
    assert (
        "inbound_routes_webhook_id_fkey" in str(exc_info.value)
        or "foreign key constraint" in str(exc_info.value).lower()
    )
