import pytest
from identity.domain.api_token import ApiToken
from seedwork.utils import generate_id

from ucp.application.use_cases.api_tokens.update_api_token_use_case import (
    UpdateApiTokenCommand,
    UpdateApiTokenUseCase,
)
from ucp.domain.constants import UcpIdPrefix as DomainIdPrefix
from ucp.domain.exceptions import UcpErrorCode
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow() -> FakeUcpUnitOfWork:
    return FakeUcpUnitOfWork()


@pytest.fixture
def update_api_token_use_case(fake_uow: FakeUcpUnitOfWork) -> UpdateApiTokenUseCase:
    return UpdateApiTokenUseCase(uow=fake_uow)


@pytest.mark.asyncio
async def test_update_api_token_missing_returns_not_found_error(
    update_api_token_use_case: UpdateApiTokenUseCase,
    fake_uow: FakeUcpUnitOfWork,
) -> None:
    command = UpdateApiTokenCommand(name="New Name", active=False)
    res = await update_api_token_use_case.execute(
        token_id=generate_id(DomainIdPrefix.TOKEN),
        tenant_id=generate_id(DomainIdPrefix.TENANT),
        command=command,
    )

    assert res.is_err
    assert res.unwrap_err().code == UcpErrorCode.TOKEN_NOT_FOUND
    assert fake_uow.committed is False


@pytest.mark.asyncio
async def test_update_api_token_renames_and_revokes_via_aggregate(
    update_api_token_use_case: UpdateApiTokenUseCase,
    fake_uow: FakeUcpUnitOfWork,
) -> None:
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    fixture_digest = "sha256_fixture_digest"
    seeded = ApiToken.create(
        tenant_id=tenant_id,
        name="Old Name",
        client_id="cli_123",
        secret_hash=fixture_digest,
    ).unwrap()
    await fake_uow.api_token_repo.save(seeded)

    command = UpdateApiTokenCommand(name="Renamed Key", active=False)
    res = await update_api_token_use_case.execute(
        token_id=seeded.id,
        tenant_id=tenant_id,
        command=command,
    )

    assert res.is_ok
    result = res.unwrap()
    assert result.name == "Renamed Key"
    assert result.active is False
    assert fake_uow.committed is True
