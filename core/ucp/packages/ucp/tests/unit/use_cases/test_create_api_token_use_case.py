from datetime import UTC, datetime, timedelta

import pytest
from identity.domain.identity_context import (
    M2M_API_KEY_PREFIX,
    M2M_CLIENT_ID_PREFIX,
    M2M_CLIENT_SECRET_PREFIX,
)
from seedwork.utils import generate_id

from ucp.application.use_cases.api_tokens.create_api_token_use_case import (
    CreateApiTokenCommand,
    CreateApiTokenUseCase,
)
from ucp.domain.constants import UcpIdPrefix as DomainIdPrefix
from ucp.domain.exceptions import UcpErrorCode
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow() -> FakeUcpUnitOfWork:
    return FakeUcpUnitOfWork()


@pytest.fixture
def create_api_token_use_case(fake_uow: FakeUcpUnitOfWork) -> CreateApiTokenUseCase:
    return CreateApiTokenUseCase(uow=fake_uow)


@pytest.mark.asyncio
async def test_create_api_token_success(
    create_api_token_use_case: CreateApiTokenUseCase,
    fake_uow: FakeUcpUnitOfWork,
) -> None:
    command = CreateApiTokenCommand(
        name="My Token", expires_at=datetime.now(UTC) + timedelta(days=30)
    )

    res = await create_api_token_use_case.execute(
        tenant_id=generate_id(DomainIdPrefix.TENANT), command=command
    )

    assert res.is_ok
    result = res.unwrap()
    assert result.name == "My Token"
    assert result.client_id.startswith(M2M_CLIENT_ID_PREFIX)
    assert result.token.startswith(f"{M2M_API_KEY_PREFIX}{M2M_CLIENT_ID_PREFIX}")
    assert f".{M2M_CLIENT_SECRET_PREFIX}" in result.token
    assert result.token.count(".") == 1
    assert fake_uow.committed is True


@pytest.mark.asyncio
async def test_create_api_token_empty_name_fails_without_commit(
    create_api_token_use_case: CreateApiTokenUseCase,
    fake_uow: FakeUcpUnitOfWork,
) -> None:
    command = CreateApiTokenCommand(name="   ")

    res = await create_api_token_use_case.execute(
        tenant_id=generate_id(DomainIdPrefix.TENANT), command=command
    )

    assert res.is_err
    assert res.unwrap_err().code == UcpErrorCode.VALIDATION_FAILED
    assert fake_uow.committed is False
