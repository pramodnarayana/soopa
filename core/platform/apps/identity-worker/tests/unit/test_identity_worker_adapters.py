import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest
from identity_worker.adapters.inbound.workers import identity_outbox_relay
from identity_worker.adapters.inbound.workers.identity_outbox_relay import IdentityOutboxRelay
from identity_worker.adapters.outbound.identity_provider.dummy_identity_provider import (
    DummyIdentityProviderPort,
)
from identity_worker.adapters.outbound.identity_provider.zitadel_identity_provider import (
    ZitadelIdentityProviderPort,
)
from identity_worker.adapters.outbound.identity_provider.zitadel_projects_adapter import (
    ZitadelProjectsAdapter,
)
from identity_worker.bootstrap.config import Settings, get_settings
from identity_worker.bootstrap.container import WorkerContainer
from identity_worker.domain.exceptions import IdentityProviderPortError
from platform_orm.models.identity import Tenant as DbTenant
from pydantic import ValidationError
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.asyncio


async def test_outbox_relay_filters_asyncpg_dsn_query_parameters(monkeypatch):
    connection = AsyncMock()
    captured_url = None

    async def connect(url):
        nonlocal captured_url
        captured_url = url
        return connection

    monkeypatch.setattr(identity_outbox_relay.asyncpg, "connect", connect)
    relay = IdentityOutboxRelay(
        processor=Mock(),
        database_url=(
            "postgresql+asyncpg://user:password@localhost/database"
            "?ssl=require&prepared_statement_cache_size=0&pgbouncer=true"
        ),
    )

    await relay._setup_listener()

    assert captured_url is not None
    query = make_url(captured_url).query
    assert query == {"sslmode": "require"}
    connection.add_listener.assert_awaited_once()


async def test_outbox_relay_stops_task_before_closing_connection():
    order = []
    processor = Mock()
    connection = AsyncMock()
    connection.remove_listener.side_effect = lambda *args: order.append("remove_listener")
    connection.close.side_effect = lambda: order.append("close")
    relay = IdentityOutboxRelay(processor=processor, database_url="postgresql://localhost/db")
    relay._connection = connection

    async def running_task():
        try:
            await asyncio.Event().wait()
        finally:
            order.append("task_cancelled")

    relay._task = asyncio.create_task(running_task())
    await asyncio.sleep(0)

    await relay.stop()
    await relay.stop()

    assert relay._task is None
    assert order[:3] == ["task_cancelled", "remove_listener", "close"]


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
    async def session_factory():
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
    monkeypatch.setenv("ZITADEL_DEFAULT_USER_PASSWORD", "test-password")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="DATABASE_URL"):
        WorkerContainer()

    get_settings.cache_clear()
