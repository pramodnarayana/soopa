from typing import cast

import pytest
from secret_store.ports.secret_store_port import SecretStorePort

from edi.application.dtos.commands import CreateAS2TradingPartnerCmd
from edi.application.use_cases.as2_partners.create_as2_partner_use_case import (
    CreateAS2PartnerUseCase,
)
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort
from edi.testing.fakes.api_fakes import FakeControlPlaneUnitOfWork


class FakeSecretStore(SecretStorePort):
    async def get_secret(self, vault_ref: str) -> str:
        return "secret"

    async def store_private_key(self, private_key_pem: bytes, category: str | None = None) -> str:
        return "key_ref"

    async def retrieve_secret(self, vault_ref: str) -> bytes:
        return b"secret"

    async def retrieve_private_key(self, vault_ref: str) -> bytes:
        return b"key"

    async def delete_secret(self, vault_ref: str) -> None:
        pass


@pytest.mark.asyncio
async def test_create_partner_event_uses_reserved_idempotency_key() -> None:
    uow = FakeControlPlaneUnitOfWork()
    use_case = CreateAS2PartnerUseCase(
        cast(ControlPlaneUnitOfWorkPort, uow),
        FakeSecretStore(),
    )

    await use_case.execute(
        "tenant-1",
        CreateAS2TradingPartnerCmd(name="Remote", as2_id="REMOTE", is_local=False),
        idempotency_key="request-1",
    )

    assert uow.as2_partners.outbox.outbox_events[0].idempotency_key == "request-1"
