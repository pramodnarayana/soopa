from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from identity.infrastructure.repositories import SQLAlchemyIdentityRepository
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def repo() -> SQLAlchemyIdentityRepository:
    session = AsyncMock()
    return SQLAlchemyIdentityRepository(session)


@pytest.mark.asyncio
async def test_get_user_id_by_email_success(repo: SQLAlchemyIdentityRepository) -> None:
    mock_result = MagicMock()
    mock_user = MagicMock()
    mock_user.id = 42
    mock_result.scalar_one_or_none.return_value = mock_user
    repo.session.execute.return_value = mock_result

    user_id = await repo.get_user_id_by_email("test@test.com")
    assert user_id == 42


@pytest.mark.asyncio
async def test_get_user_id_by_email_not_found(repo: SQLAlchemyIdentityRepository) -> None:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    repo.session.execute.return_value = mock_result

    user_id = await repo.get_user_id_by_email("unknown@test.com")
    assert user_id is None


@pytest.mark.asyncio
async def test_get_tenant_id_for_user_success(repo: SQLAlchemyIdentityRepository) -> None:
    mock_result = MagicMock()
    mock_tenant_user = MagicMock()
    mock_tenant_user.tenant_id = 101
    mock_result.scalar_one_or_none.return_value = mock_tenant_user
    repo.session.execute.return_value = mock_result

    tenant_id = await repo.get_tenant_id_for_user(42)
    assert tenant_id == 101


@pytest.mark.asyncio
async def test_get_tenant_id_for_user_not_found(repo: SQLAlchemyIdentityRepository) -> None:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    repo.session.execute.return_value = mock_result

    tenant_id = await repo.get_tenant_id_for_user(99)
    assert tenant_id is None


@pytest.mark.asyncio
async def test_provision_tenant_missing_shard(repo: SQLAlchemyIdentityRepository) -> None:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    repo.session.execute.return_value = mock_result

    with pytest.raises(RuntimeError, match="Default shard not found for provisioning"):
        await repo.provision_tenant_for_user("test@test.com", "Test Name")


@pytest.mark.asyncio
async def test_provision_tenant_success(repo: SQLAlchemyIdentityRepository) -> None:
    # Setup shard lookup success
    mock_shard_result = MagicMock()
    mock_shard = MagicMock()
    mock_shard.id = 1
    mock_shard_result.scalar_one_or_none.return_value = mock_shard
    repo.session.execute.return_value = mock_shard_result

    # We need to mock User.id and Tenant.id assignment on flush
    # In SQLAlchemy, flush assigns IDs to pending objects.
    pending_objects = []

    def mock_add(entity: Any) -> None:
        pending_objects.append(entity)

    async def mock_flush() -> None:
        for entity in pending_objects:
            if hasattr(entity, "email"):
                entity.id = 42
            elif hasattr(entity, "shard_id"):
                entity.id = 101
        pending_objects.clear()

    repo.session.add = MagicMock(side_effect=mock_add)
    repo.session.flush.side_effect = mock_flush

    tenant_id = await repo.provision_tenant_for_user("test@test.com", "Test Name")

    assert tenant_id == 101
    assert repo.session.add.call_count == 3  # User, Tenant, TenantUser
    assert repo.session.flush.call_count == 2
    repo.session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_provision_tenant_integrity_error_success(repo: SQLAlchemyIdentityRepository) -> None:
    # Setup shard lookup success
    mock_shard_result = MagicMock()
    mock_shard = MagicMock()
    mock_shard.id = 1
    mock_shard_result.scalar_one_or_none.return_value = mock_shard
    repo.session.execute.return_value = mock_shard_result

    repo.session.add = MagicMock()
    # Simulate IntegrityError on first flush (concurrent user creation)
    repo.session.flush.side_effect = [IntegrityError("mock", "mock", "mock"), None]

    with (
        patch.object(repo, "get_user_id_by_email", return_value=42) as mock_get_user,
        patch.object(repo, "get_tenant_id_for_user", return_value=101) as mock_get_tenant,
    ):
        tenant_id = await repo.provision_tenant_for_user("test@test.com", "Test Name")

        assert tenant_id == 101
        repo.session.rollback.assert_called_once()
        mock_get_user.assert_called_once_with("test@test.com")
        mock_get_tenant.assert_called_once_with(42)


@pytest.mark.asyncio
async def test_provision_tenant_integrity_error_no_user(repo: SQLAlchemyIdentityRepository) -> None:
    # Setup shard lookup success
    mock_shard_result = MagicMock()
    mock_shard = MagicMock()
    mock_shard.id = 1
    mock_shard_result.scalar_one_or_none.return_value = mock_shard
    repo.session.execute.return_value = mock_shard_result

    repo.session.add = MagicMock()
    # Simulate IntegrityError on first flush (concurrent user creation)
    repo.session.flush.side_effect = IntegrityError("mock", "mock", "mock")

    with (
        patch.object(repo, "get_user_id_by_email", return_value=None),
        pytest.raises(RuntimeError, match="Failed to re-fetch user after IntegrityError"),
    ):
        await repo.provision_tenant_for_user("test@test.com", "Test Name")


@pytest.mark.asyncio
async def test_provision_tenant_integrity_error_no_tenant(
    repo: SQLAlchemyIdentityRepository,
) -> None:
    # Setup shard lookup success
    mock_shard_result = MagicMock()
    mock_shard = MagicMock()
    mock_shard.id = 1
    mock_shard_result.scalar_one_or_none.return_value = mock_shard
    repo.session.execute.return_value = mock_shard_result

    repo.session.add = MagicMock()
    # Simulate IntegrityError on first flush (concurrent user creation)
    repo.session.flush.side_effect = IntegrityError("mock", "mock", "mock")

    with (
        patch.object(repo, "get_user_id_by_email", return_value=42),
        patch.object(repo, "get_tenant_id_for_user", return_value=None),
        pytest.raises(RuntimeError, match="Concurrent provisioning incomplete. Please retry."),
    ):
        await repo.provision_tenant_for_user("test@test.com", "Test Name")
