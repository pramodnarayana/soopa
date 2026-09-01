import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from edi.application.dto import CreateAS2TradingPartnerCmd
from edi.application.use_cases.as2_partners.create_as2_partner_use_case import (
    CreateAS2PartnerUseCase,
)
from edi.domain.exceptions import IdempotencyConflictError


@pytest.mark.asyncio
async def test_existing_idempotency_key_reuses_partner_before_secret_provisioning():
    command = CreateAS2TradingPartnerCmd(
        name="Partner",
        as2_id="PARTNER",
        is_local=True,
        private_key_vault_ref="vault-key",
    )
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "tenant_id": "tenant-1",
                "name": command.name,
                "as2_id": command.as2_id,
                "is_local": command.is_local,
                "url": command.url,
                "public_cert_pem": command.public_cert_pem,
                "public_cert_vault_ref": command.public_cert_vault_ref,
                "private_key_vault_ref": command.private_key_vault_ref,
                "private_key_digest": None,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    now = datetime.now(UTC)
    uow = AsyncMock()
    uow.control_plane_outbox.create_reservation.side_effect = IdempotencyConflictError()
    uow.control_plane_outbox.get_event_by_idempotency_key.return_value = SimpleNamespace(
        payload={"fingerprint": fingerprint, "resource_id": "partner-1"}
    )
    uow.as2_partners.get_as2_partner.return_value = SimpleNamespace(
        name="Partner",
        as2_id="PARTNER",
        is_local=True,
        created_at=now,
        updated_at=now,
    )
    secret_store = AsyncMock()
    use_case = CreateAS2PartnerUseCase(uow, secret_store)

    partner = await use_case.execute("tenant-1", command, idempotency_key="request-1")

    assert partner.id == "partner-1"
    uow.as2_partners.create_as2_identity.assert_not_awaited()
    secret_store.store_private_key.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_idempotency_key_finalizes_reservation_through_outbox_repository():
    command = CreateAS2TradingPartnerCmd(
        name="Partner",
        as2_id="PARTNER",
    )
    uow = AsyncMock()
    secret_store = AsyncMock()
    use_case = CreateAS2PartnerUseCase(uow, secret_store)

    partner = await use_case.execute("tenant-1", command, idempotency_key="request-1")

    uow.as2_partners.save.assert_awaited_once_with(partner)
    event = uow.control_plane_outbox.publish_outbox_event.await_args.args[0]
    assert event.resource_id == partner.id
    assert event.explicit_idempotency_key is None
    uow.control_plane_outbox.publish_outbox_event.assert_awaited_once_with(
        event, idempotency_key="request-1"
    )
