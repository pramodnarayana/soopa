import pytest
from identity.domain.api_token import ApiToken
from seedwork.utils import generate_id

from ucp.application.use_cases.api_tokens.delete_api_token_use_case import DeleteApiTokenUseCase
from ucp.domain.constants import UcpIdPrefix as DomainIdPrefix
from ucp.domain.exceptions import UcpErrorCode
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow() -> FakeUcpUnitOfWork:
    return FakeUcpUnitOfWork()


@pytest.fixture
def delete_api_token_use_case(fake_uow: FakeUcpUnitOfWork) -> DeleteApiTokenUseCase:
    return DeleteApiTokenUseCase(uow=fake_uow)


@pytest.mark.asyncio
async def test_delete_api_token_success(
    delete_api_token_use_case: DeleteApiTokenUseCase,
    fake_uow: FakeUcpUnitOfWork,
) -> None:
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    fixture_digest = "sha256_fixture_digest"
    seeded = ApiToken.create(
        tenant_id=tenant_id,
        name="Key To Delete",
        client_id="cli_del",
        secret_hash=fixture_digest,
    ).unwrap()
    await fake_uow.api_token_repo.save(seeded)

    res = await delete_api_token_use_case.execute(
        token_id=seeded.id,
        tenant_id=tenant_id,
    )
    assert res.is_ok
    assert fake_uow.committed is True


@pytest.mark.asyncio
async def test_delete_api_token_missing_returns_not_found_error(
    delete_api_token_use_case: DeleteApiTokenUseCase,
    fake_uow: FakeUcpUnitOfWork,
) -> None:
    res = await delete_api_token_use_case.execute(
        token_id=generate_id(DomainIdPrefix.TOKEN),
        tenant_id=generate_id(DomainIdPrefix.TENANT),
    )
    assert res.is_err
    assert res.unwrap_err().code == UcpErrorCode.TOKEN_NOT_FOUND
    assert fake_uow.committed is False
