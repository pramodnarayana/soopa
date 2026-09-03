from typing import cast
from unittest.mock import AsyncMock

import pytest
from secret_store.ports.secret_store_port import SecretStorePort

from edi.application.dtos.commands import CreateAS2TradingPartnerCmd
from edi.application.use_cases.as2_partners.create_as2_partner_use_case import (
    CreateAS2PartnerUseCase,
)
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort
from edi.testing.fakes.api_fakes import FakeControlPlaneUnitOfWork


@pytest.mark.asyncio
async def test_create_partner_event_uses_reserved_idempotency_key() -> None:
    uow = FakeControlPlaneUnitOfWork()
    use_case = CreateAS2PartnerUseCase(
        cast(ControlPlaneUnitOfWorkPort, uow),
        cast(SecretStorePort, AsyncMock()),
    )

    await use_case.execute(
        "tenant-1",
        CreateAS2TradingPartnerCmd(name="Remote", as2_id="REMOTE", is_local=False),
        idempotency_key="request-1",
    )

    assert uow.as2_partners.outbox.outbox_events[0].idempotency_key == "request-1"
