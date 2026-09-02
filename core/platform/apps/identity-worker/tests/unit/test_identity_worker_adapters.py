import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest
from database.models.identity import Tenant as DbTenant
from database.models.identity import User as DbUser
from identity.domain.constants import UserStatus
from identity_worker.adapters.outbound.identity_provider.dummy_identity_provider import (
    DummyIdentityProviderPort,
)
from identity_worker.adapters.outbound.identity_provider.zitadel_identity_provider import (
    ZitadelIdentityProviderPort,
)
from identity_worker.adapters.outbound.identity_provider.zitadel_projects_adapter import (
    ZitadelProjectsAdapter,
)
from identity_worker.application.use_cases.identity_sync_service import (
    IdentitySyncService,
    StateConflictError,
)
from identity_worker.bootstrap.config import Settings, get_settings
from identity_worker.bootstrap.container import UserRoleAssignedPayload, WorkerContainer
from identity_worker.domain.exceptions import IdentityProviderPortError
from pydantic import ValidationError

pytestmark = pytest.mark.asyncio


async def test_dummy_identity_provider_returns_unique_user_ids():
    provider = DummyIdentityProviderPort()

    first_id = await provider.create_user("org", "a@example.com", "A", "User")
    second_id = await provider.create_user("org", "b@example.com", "B", "User")

    assert first_id != second_id


async def test_zitadel_roles_search_fetches_every_page():
    first_response = Mock(status_code=200)
    first_response.json.return_value = {
        "details": {"totalResult": "101"},
        "result": [{"key": f"role-{index}"} for index in range(100)],
    }
    second_response = Mock(status_code=200)
    second_response.json.return_value = {
        "details": {"totalResult": "101"},
        "result": [{"key": "role-100"}],
    }
    adapter = object.__new__(ZitadelProjectsAdapter)
    adapter.ucp_project_id = "project-1"
    adapter.fetch_with_auth = AsyncMock(side_effect=[first_response, second_response])

    roles = await adapter.get_roles()

    assert len(roles) == 101
    assert adapter.fetch_with_auth.await_args_list[0].kwargs["json"]["query"] == {
        "offset": 0,
        "limit": 100,
    }
    assert adapter.fetch_with_auth.await_args_list[1].kwargs["json"]["query"] == {
        "offset": 100,
        "limit": 100,
    }


async def test_zitadel_search_stops_after_maximum_page_count():
    full_response = Mock(status_code=200)
    full_response.json.return_value = {"result": [{} for _ in range(100)]}
    adapter = object.__new__(ZitadelProjectsAdapter)
    adapter._MAX_SEARCH_PAGES = 1
    adapter.fetch_with_auth = AsyncMock(return_value=full_response)

    with pytest.raises(IdentityProviderPortError, match="exceeded 1 pages"):
        await adapter._search_all("/management/v1/users/_search")

    adapter.fetch_with_auth.assert_awaited_once()


async def test_user_role_payload_accepts_missing_idp_mapping():
    payload = UserRoleAssignedPayload.model_validate(
        {"user_id": "user-1", "tenant_id": "tenant-1", "role_name": "admin"}
    )

    assert payload.idp_user_id is None


async def test_role_assignment_retries_until_idp_mapping_exists():
    tenant = DbTenant(
        id="tenant-1", name="Tenant One", slug="tenant-one", idp_tenant_id="idp-tenant-1"
    )
    user = DbUser(id="user-1", email="user@example.com", name="User", status=UserStatus.ACTIVE)
    tenant_result = Mock()
    tenant_result.scalar_one_or_none.return_value = tenant
    user_result = Mock()
    user_result.scalar_one_or_none.return_value = user
    session = AsyncMock()
    session.execute.side_effect = [tenant_result, user_result]

    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncMock]:
        yield session

    user_provider = AsyncMock()
    service = IdentitySyncService(AsyncMock(), user_provider, session_factory)

    with pytest.raises(StateConflictError, match="not fully provisioned"):
        await service.handle_user_role_assigned(
            user_id="user-1", idp_user_id=None, tenant_id="tenant-1", role="admin"
        )

    user.idp_user_id = "idp-user-1"
    session.execute.side_effect = [tenant_result, user_result]
    await service.handle_user_role_assigned(
        user_id="user-1", idp_user_id=None, tenant_id="tenant-1", role="admin"
    )

    user_provider.assign_tenant_role.assert_awaited_once_with(
        user_id="idp-user-1", org_id="idp-tenant-1", role="admin"
    )


async def test_user_creation_completes_compensation_when_cancelled_during_cleanup():
    local_user = DbUser(
        id="user-1", email="user@example.com", name="User", status=UserStatus.ACTIVE
    )
    tenant = DbTenant(
        id="tenant-1", name="Tenant One", slug="tenant-one", idp_tenant_id="idp-tenant-1"
    )
    user_result = Mock()
    user_result.scalar_one_or_none.return_value = local_user
    tenant_result = Mock()
    tenant_result.scalar_one_or_none.return_value = tenant
    session = AsyncMock()
    session.execute.side_effect = [user_result, tenant_result]

    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncMock]:
        yield session

    delete_started = asyncio.Event()
    allow_delete = asyncio.Event()

    async def delete_user(_user_id: str) -> None:
        delete_started.set()
        await allow_delete.wait()

    user_provider = AsyncMock()
    user_provider.create_user.return_value = "idp-user-1"
    user_provider.assign_tenant_role.side_effect = RuntimeError("role assignment failed")
    user_provider.delete_user.side_effect = delete_user
    service = IdentitySyncService(AsyncMock(), user_provider, session_factory)

    sync_task = asyncio.create_task(
        service.handle_user_created(
            user_id="user-1",
            tenant_id="tenant-1",
            email="user@example.com",
            first_name="Test",
            last_name="User",
            role="admin",
        )
    )
    await delete_started.wait()
    sync_task.cancel()
    allow_delete.set()

    with pytest.raises(RuntimeError, match="role assignment failed"):
        await sync_task

    session.rollback.assert_awaited_once()
    user_provider.delete_user.assert_awaited_once_with("idp-user-1")


async def test_zitadel_tenant_sync_does_not_persist_without_project_grant():
    tenant = DbTenant(
        id="tenant-1",
        name="Tenant One",
        slug="tenant-one",
        idp_tenant_id=None,
    )
    result = Mock()
    result.scalar_one_or_none.return_value = tenant
    session = AsyncMock()
    session.execute.return_value = result

    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncMock]:
        yield session

    org_provider = AsyncMock()
    org_provider.create_organization.return_value = ("org-1", False)
    provider = ZitadelIdentityProviderPort(org_provider, session_factory)

    with pytest.raises(IdentityProviderPortError, match="project grant"):
        await provider.sync_tenant("tenant-1")

    assert tenant.idp_tenant_id is None
    session.commit.assert_not_awaited()


async def test_zitadel_default_password_is_required(monkeypatch):
    monkeypatch.delenv("ZITADEL_DEFAULT_USER_PASSWORD", raising=False)

    with pytest.raises(ValidationError, match="zitadel_default_user_password"):
        Settings(_env_file=None)


async def test_worker_container_requires_database_url(monkeypatch):

    bad_settings = Settings(
        database_url="",
        zitadel_default_user_password="not-for-production",  # noqa: S106 - test credential
    )
    with pytest.raises(ValueError, match="database_url"):
        WorkerContainer(settings=bad_settings)

    get_settings.cache_clear()
