from typing import cast

import pytest
from secret_store.ports.secret_store_port import SecretStorePort

from edi.application.use_cases.as2_partners.create_as2_partner_use_case import (
    CreateAS2PartnerUseCase,
    CreateAS2TradingPartnerCmd,
)
from edi.domain.exceptions import EdiErrorCode
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

    res = await use_case.execute(
        "tenant-1",
        CreateAS2TradingPartnerCmd(name="Remote", as2_id="REMOTE", is_local=False),
        idempotency_key="request-1",
    )
    assert res.is_ok

    reservation = await uow.control_plane_outbox.get_event_by_idempotency_key("request-1")
    assert reservation is not None
    assert reservation.idempotency_key == "request-1"


@pytest.mark.asyncio
async def test_create_partner_returns_first_class_errors_on_missing_local_key_and_duplicate() -> (
    None
):
    uow = FakeControlPlaneUnitOfWork()
    use_case = CreateAS2PartnerUseCase(
        cast(ControlPlaneUnitOfWorkPort, uow),
        FakeSecretStore(),
    )

    missing_key = await use_case.execute(
        "tenant-1",
        CreateAS2TradingPartnerCmd(name="Local Missing Key", as2_id="LOCAL_1", is_local=True),
    )
    assert missing_key.is_err
    assert missing_key.unwrap_err().code == EdiErrorCode.VALIDATION_FAILED

    first_ok = await use_case.execute(
        "tenant-1",
        CreateAS2TradingPartnerCmd(name="Remote 1", as2_id="DUP_AS2", is_local=False),
    )
    assert first_ok.is_ok

    dup_err = await use_case.execute(
        "tenant-1",
        CreateAS2TradingPartnerCmd(name="Remote 2", as2_id="DUP_AS2", is_local=False),
    )
    assert dup_err.is_err
    assert dup_err.unwrap_err().code == EdiErrorCode.PARTNER_ALREADY_EXISTS
