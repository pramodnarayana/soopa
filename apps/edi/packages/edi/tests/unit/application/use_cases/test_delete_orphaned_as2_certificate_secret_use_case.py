from typing import cast

import pytest
from identity.domain.identity_context import PLATFORM_TENANT_ID
from secret_store.testing.fakes.in_memory_vault import InMemoryVaultAdapter

from edi.application.use_cases.as2_partners import (
    DeleteOrphanedAS2CertificateSecretCmd,
    DeleteOrphanedAS2CertificateSecretUseCase,
)
from edi.config.constants import SecretCategory
from edi.domain.exceptions import EdiErrorCode
from edi.domain.partner.as2.partner import AS2Partner
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort
from edi.testing.fakes.api_fakes import FakeControlPlaneUnitOfWork


@pytest.mark.asyncio
async def test_delete_orphaned_as2_certificate_secret_deletes_unreferenced_secret() -> None:
    uow = FakeControlPlaneUnitOfWork()
    vault = InMemoryVaultAdapter()
    ref = await vault.store_private_key(b"PRIVATE_KEY_PEM", category=SecretCategory.AS2_KEY.value)

    use_case = DeleteOrphanedAS2CertificateSecretUseCase(
        uow=cast(ControlPlaneUnitOfWorkPort, uow),
        secret_store=vault,
    )
    res = await use_case.execute(DeleteOrphanedAS2CertificateSecretCmd(vault_ref=f"vault://{ref}"))

    assert res.is_ok
    assert ref not in vault.secrets


@pytest.mark.asyncio
async def test_delete_orphaned_as2_certificate_secret_rejects_foreign_prefix_and_in_use_refs() -> (
    None
):
    uow = FakeControlPlaneUnitOfWork()
    vault = InMemoryVaultAdapter()
    ref = await vault.store_private_key(b"PRIVATE_KEY_PEM", category=SecretCategory.AS2_KEY.value)

    use_case = DeleteOrphanedAS2CertificateSecretUseCase(
        uow=cast(ControlPlaneUnitOfWorkPort, uow),
        secret_store=vault,
    )

    foreign_res = await use_case.execute(
        DeleteOrphanedAS2CertificateSecretCmd(vault_ref=f"other-service/{ref}")
    )
    assert foreign_res.is_err
    assert foreign_res.unwrap_err().code == EdiErrorCode.VALIDATION_FAILED

    partner_res = AS2Partner.create(
        tenant_id=PLATFORM_TENANT_ID,
        as2_id="STATION_1",
        name="Station 1",
        is_local=True,
        private_key_vault_ref=ref,
    )
    assert partner_res.is_ok
    await uow.as2_partners.save(partner_res.unwrap())

    in_use_res = await use_case.execute(DeleteOrphanedAS2CertificateSecretCmd(vault_ref=f"/{ref}/"))
    assert in_use_res.is_err
    assert in_use_res.unwrap_err().code == EdiErrorCode.VALIDATION_FAILED
    assert ref in vault.secrets
