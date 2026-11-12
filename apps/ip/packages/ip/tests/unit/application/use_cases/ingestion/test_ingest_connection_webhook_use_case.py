"""Pure zero-mock unit tests for IngestConnectionWebhookUseCase."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Sequence
from types import TracebackType

import pytest
from identity.domain.constants import IdentityIdPrefix
from ip.engine.application.use_cases.ingestion.ingest_connection_webhook_use_case import (
    IngestConnectionWebhookCommand,
    IngestConnectionWebhookUseCase,
)
from ip.engine.application.use_cases.ingestion.receive_push_use_case import (
    ReceivePushCommand,
    ReceivePushExecutorPort,
    ReceivePushResultDTO,
)
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.connection.enums import AuthType, ConnectionStatus
from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.exceptions import (
    DuplicateConnectionFingerprintError,
    IpErrorCode,
    Result,
    TenantShardNotFoundError,
)
from ip.engine.ports.outbound.connection_entity_repository_port import (
    ConnectionEntityRepositoryPort,
)
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.stitch_repository_port import StitchRepositoryPort
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort
from ip.engine.ports.outbound.transformation_repository_port import (
    TransformationRepositoryPort,
)
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)
from seedwork.utils import generate_id


class _InMemoryConnectionRepo(ConnectionRepositoryPort):
    def __init__(self) -> None:
        self.items: dict[str, Connection] = {}

    async def save(
        self, connection: Connection
    ) -> Result[Connection, DuplicateConnectionFingerprintError]:
        self.items[connection.id] = connection
        return Result.ok(connection)

    async def get_by_id(self, connection_id: str) -> Connection | None:
        return self.items.get(connection_id)

    async def get_by_fingerprint(self, tenant_id: str, fingerprint: str) -> Connection | None:
        _ = (tenant_id, fingerprint)
        return None

    async def list_by_tenant(
        self, tenant_id: str, status: ConnectionStatus | None = None
    ) -> Sequence[Connection]:
        _ = (tenant_id, status)
        return list(self.items.values())


class _StubControlPlaneUoW(IpControlPlaneUnitOfWorkPort):
    connections: _InMemoryConnectionRepo
    entities: ConnectionEntityRepositoryPort
    sync_runs: SyncRunRepositoryPort
    transformations: TransformationRepositoryPort
    stitches: StitchRepositoryPort

    def __init__(self) -> None:
        self.connections = _InMemoryConnectionRepo()

    async def __aenter__(self) -> _StubControlPlaneUoW:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        _ = (exc_type, exc_val, exc_tb)

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _StubDataPlaneUoW:
    def __init__(self) -> None:
        self.entered = False


class _StubDataPlaneUoWProvider(IpDataPlaneUnitOfWorkProviderPort):
    def __init__(
        self,
        dp_uow: IpDataPlaneUnitOfWorkPort,
        *,
        missing_shard_tenant_id: str | None = None,
    ) -> None:
        self._dp_uow = dp_uow
        self._missing_shard_tenant_id = missing_shard_tenant_id

    async def resolve_shard_info(
        self, tenant_id: str
    ) -> Result[tuple[str, str], TenantShardNotFoundError]:
        if tenant_id == self._missing_shard_tenant_id:
            return Result.err(TenantShardNotFoundError.for_tenant(tenant_id))
        return Result.ok(("shard-01", "in-memory://shard-01"))

    @contextlib.asynccontextmanager
    async def get_data_plane_uow(
        self,
        tenant_id: str,
        shard_id: str,
        shard_dsn: str,
    ) -> AsyncIterator[IpDataPlaneUnitOfWorkPort]:
        _ = (tenant_id, shard_id, shard_dsn)
        yield self._dp_uow


class _RecordingPushExecutor(ReceivePushExecutorPort):
    def __init__(self) -> None:
        self.commands: list[ReceivePushCommand] = []

    async def execute(self, command: ReceivePushCommand) -> ReceivePushResultDTO:
        self.commands.append(command)
        return ReceivePushResultDTO(
            status_code=202,
            headers={},
            body={"status": "ACCEPTED"},
            trace_id=generate_id(IpIdPrefix.TRACE.value),
            record_id=generate_id(IpIdPrefix.INBOUND_RECORD.value),
            payload_size_bytes=len(command.raw_payload),
            is_inlined=True,
        )


def _dummy_dp_uow() -> IpDataPlaneUnitOfWorkPort:
    class _EmptyDataPlaneUoW(IpDataPlaneUnitOfWorkPort):
        def __init__(self) -> None:
            self.committed = False

        async def __aenter__(self) -> _EmptyDataPlaneUoW:
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: TracebackType | None,
        ) -> None:
            _ = (exc_type, exc_val, exc_tb)

        async def commit(self) -> None:
            self.committed = True

        async def rollback(self) -> None:
            return None

        async def record_idempotency(self, tenant_id: str, idempotency_key: str) -> bool:
            _ = (tenant_id, idempotency_key)
            return True

    return _EmptyDataPlaneUoW()


@pytest.mark.asyncio
async def test_ingest_webhook_rejects_missing_or_mismatched_connection() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    other_tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    conn_id = generate_id(IpIdPrefix.CONNECTION.value)

    cp_uow = _StubControlPlaneUoW()
    dp_uow = _dummy_dp_uow()
    executor = _RecordingPushExecutor()
    use_case = IngestConnectionWebhookUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow_provider=_StubDataPlaneUoWProvider(dp_uow),
        push_executor_factory=lambda _uow: executor,
    )

    missing_res = await use_case.execute(
        IngestConnectionWebhookCommand(
            tenant_id=tenant_id,
            app_id="http",
            connection_id=conn_id,
            stream_name="events",
            raw_payload=b'{"id":"1"}',
            headers={},
        )
    )
    assert missing_res.is_err
    assert missing_res.unwrap_err().code == IpErrorCode.CONNECTION_NOT_FOUND

    conn = Connection(
        id=conn_id,
        tenant_id=tenant_id,
        app_id="http",
        name="Webhook Source",
        auth_type=AuthType.API_KEY,
        connection_fingerprint="fp_wh",
        status=ConnectionStatus.ACTIVE,
    )
    await cp_uow.connections.save(conn)

    wrong_tenant_res = await use_case.execute(
        IngestConnectionWebhookCommand(
            tenant_id=other_tenant_id,
            app_id="http",
            connection_id=conn_id,
            stream_name="events",
            raw_payload=b'{"id":"1"}',
            headers={},
        )
    )
    assert wrong_tenant_res.is_err
    assert wrong_tenant_res.unwrap_err().code == IpErrorCode.CONNECTION_NOT_FOUND

    wrong_app_res = await use_case.execute(
        IngestConnectionWebhookCommand(
            tenant_id=tenant_id,
            app_id="salesforce",
            connection_id=conn_id,
            stream_name="events",
            raw_payload=b'{"id":"1"}',
            headers={},
        )
    )
    assert wrong_app_res.is_err
    assert wrong_app_res.unwrap_err().code == IpErrorCode.CONNECTION_NOT_FOUND
    assert executor.commands == []


@pytest.mark.asyncio
async def test_ingest_webhook_rejects_deactivated_connection_or_missing_shard() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    deact_conn_id = generate_id(IpIdPrefix.CONNECTION.value)
    active_conn_id = generate_id(IpIdPrefix.CONNECTION.value)

    cp_uow = _StubControlPlaneUoW()
    await cp_uow.connections.save(
        Connection(
            id=deact_conn_id,
            tenant_id=tenant_id,
            app_id="http",
            name="Deactivated Source",
            auth_type=AuthType.API_KEY,
            connection_fingerprint="fp_deact",
            status=ConnectionStatus.DEACTIVATED,
        )
    )
    await cp_uow.connections.save(
        Connection(
            id=active_conn_id,
            tenant_id=tenant_id,
            app_id="http",
            name="Unsharded Source",
            auth_type=AuthType.API_KEY,
            connection_fingerprint="fp_active",
            status=ConnectionStatus.ACTIVE,
        )
    )

    dp_uow = _dummy_dp_uow()
    executor = _RecordingPushExecutor()
    use_case = IngestConnectionWebhookUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow_provider=_StubDataPlaneUoWProvider(
            dp_uow,
            missing_shard_tenant_id=tenant_id,
        ),
        push_executor_factory=lambda _uow: executor,
    )

    deact_res = await use_case.execute(
        IngestConnectionWebhookCommand(
            tenant_id=tenant_id,
            app_id="http",
            connection_id=deact_conn_id,
            stream_name="events",
            raw_payload=b'{"id":"1"}',
            headers={},
        )
    )
    assert deact_res.is_err
    assert deact_res.unwrap_err().code == IpErrorCode.CONNECTION_DEACTIVATED

    shard_err_res = await use_case.execute(
        IngestConnectionWebhookCommand(
            tenant_id=tenant_id,
            app_id="http",
            connection_id=active_conn_id,
            stream_name="events",
            raw_payload=b'{"id":"1"}',
            headers={},
        )
    )
    assert shard_err_res.is_err
    assert shard_err_res.unwrap_err().code == IpErrorCode.TENANT_SHARD_NOT_FOUND


@pytest.mark.asyncio
async def test_ingest_webhook_delegates_active_connection_to_push_executor() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    conn_id = generate_id(IpIdPrefix.CONNECTION.value)

    cp_uow = _StubControlPlaneUoW()
    await cp_uow.connections.save(
        Connection(
            id=conn_id,
            tenant_id=tenant_id,
            app_id="http",
            name="Active Webhook Source",
            auth_type=AuthType.API_KEY,
            connection_fingerprint="fp_ok",
            status=ConnectionStatus.ACTIVE,
        )
    )

    dp_uow = _dummy_dp_uow()
    executor = _RecordingPushExecutor()
    use_case = IngestConnectionWebhookUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow_provider=_StubDataPlaneUoWProvider(dp_uow),
        push_executor_factory=lambda _uow: executor,
    )

    res = await use_case.execute(
        IngestConnectionWebhookCommand(
            tenant_id=tenant_id,
            app_id="http",
            connection_id=conn_id,
            stream_name="orders",
            raw_payload=b'{"order_id":"ORD-1"}',
            headers={"content-type": "application/json"},
            external_event_id="evt_ext_1",
            correlation_id="corr_ext_1",
        )
    )
    assert res.is_ok
    dto = res.unwrap()
    assert dto.status_code == 202
    assert len(executor.commands) == 1
    assert executor.commands[0].stream_name == "orders"
    assert executor.commands[0].external_event_id == "evt_ext_1"
    assert executor.commands[0].correlation_id == "corr_ext_1"
