from collections.abc import AsyncGenerator
from typing import cast

import pytest
from database.router import DatabaseRouter
from database.types import GlobalSession, TenantSession
from edi.adapters.outbound.database.replication_adapter import SqlAlchemyReplicationAdapter
from edi.domain.replication import (
    PermanentProvisioningError,
    TransientProvisioningError,
)
from edi.ports.outbound.tenant_port import TenantPort


class ErrorTenantPort(TenantPort):
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def resolve_shard(self, tenant_id: str) -> tuple[str, str]:
        raise self._exc


class DummyDatabaseRouter(DatabaseRouter):
    def __init__(self) -> None:
        pass

    async def _empty_global_session(self) -> AsyncGenerator[GlobalSession, None]:
        if False:
            yield cast(GlobalSession, None)

    async def _empty_tenant_session(self) -> AsyncGenerator[TenantSession, None]:
        if False:
            yield cast(TenantSession, None)

    def get_global_session(self) -> AsyncGenerator[GlobalSession, None]:
        return self._empty_global_session()

    def get_tenant_session(
        self, tenant_id: str, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        return self._empty_tenant_session()


@pytest.mark.parametrize(
    "exc,expected_error_cls",
    [
        (TimeoutError("Connection timed out"), TransientProvisioningError),
        (ConnectionError("Network is unreachable"), TransientProvisioningError),
        (ValueError("Unknown tenant"), PermanentProvisioningError),
        (KeyError("Tenant missing from registry"), PermanentProvisioningError),
    ],
)
async def test_get_sessions_error_classification(
    exc: Exception, expected_error_cls: type[Exception]
) -> None:
    port = ErrorTenantPort(exc)
    router = DummyDatabaseRouter()
    adapter = SqlAlchemyReplicationAdapter(tenant_port=port, db_router=router)

    with pytest.raises(expected_error_cls):
        async with adapter._get_sessions("tenant_123"):
            pass


@pytest.mark.parametrize(
    "exc,expected_error_cls",
    [
        (TimeoutError("Connection timed out"), TransientProvisioningError),
        (ConnectionError("Network is unreachable"), TransientProvisioningError),
        (ValueError("Unknown tenant"), PermanentProvisioningError),
        (KeyError("Tenant missing from registry"), PermanentProvisioningError),
    ],
)
async def test_get_tenant_session_error_classification(
    exc: Exception, expected_error_cls: type[Exception]
) -> None:
    port = ErrorTenantPort(exc)
    router = DummyDatabaseRouter()
    adapter = SqlAlchemyReplicationAdapter(tenant_port=port, db_router=router)

    with pytest.raises(expected_error_cls):
        async with adapter._get_tenant_session("tenant_123"):
            pass
