from datetime import UTC, datetime

import pytest
from identity.domain.constants import DomainIdPrefix as IamPrefix
from identity.domain.models.api_token_models import CreateApiTokenCommand
from seedwork.utils import generate_id

from ucp.application.use_cases.api_tokens.create_api_token_use_case import CreateApiTokenUseCase
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow():
    return FakeUcpUnitOfWork()


@pytest.fixture
def create_api_token_use_case(fake_uow):
    return CreateApiTokenUseCase(uow=fake_uow)


@pytest.mark.asyncio
async def test_create_api_token_success(create_api_token_use_case, fake_uow):
    command = CreateApiTokenCommand(name="My Token", expires_at=datetime.now(UTC))

    result = await create_api_token_use_case.execute(
        tenant_id=generate_id(IamPrefix.TENANT), command=command
    )

    assert result.name == "My Token"
    assert result.token.startswith("sp_api_")
    assert result.token.count(".") == 1
    assert fake_uow.committed is True
