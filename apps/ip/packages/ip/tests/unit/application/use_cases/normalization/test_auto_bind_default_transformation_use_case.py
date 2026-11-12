"""Pure zero-mock unit tests for AutoBindDefaultTransformationOnEntitySubscribedUseCase."""

from __future__ import annotations

import pytest
from identity.domain.constants import IdentityIdPrefix
from ip.engine.application.use_cases.connections.discover_catalog_use_case import (
    DiscoverCatalogExecutorPort,
)
from ip.engine.application.use_cases.normalization.auto_bind_default_transformation_use_case import (
    AutoBindDefaultTransformationCommand,
    AutoBindDefaultTransformationOnEntitySubscribedUseCase,
)
from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.dispatch.enums import FailureDisposition
from ip.engine.domain.exceptions import (
    ConnectionNotFoundError,
    IpError,
    IpErrorCode,
    Result,
    UpstreamHttpError,
)
from ip.engine.domain.normalization.registries import TransformerRegistry
from ip.engine.domain.normalization.transformation import (
    CanonicalDraft,
    ReplicaSnapshot,
    Transformation,
    TransformationContext,
    TransformationResult,
)
from ip.engine.ports.outbound.connection_entity_repository_port import (
    ConnectionEntityRepositoryPort,
)
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.connector_port import DiscoveredCatalogDTO, StreamSchemaDTO
from ip.engine.ports.outbound.stitch_repository_port import StitchRepositoryPort
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort
from ip.engine.ports.outbound.transformation_repository_port import (
    TransformationRepositoryPort,
)
from ip.engine.ports.outbound.transformer_port import TransformerPort
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort
from seedwork.utils import generate_id


class _DefaultOrdersTransformer(TransformerPort):
    @property
    def transformation_id(self) -> str:
        return "canonical.orders"

    @property
    def transformation_version(self) -> int:
        return 2

    @property
    def target_types(self) -> tuple[str, ...]:
        return ("canonical.order.v1",)

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult:
        _ = context
        return TransformationResult(
            drafts=(
                CanonicalDraft(
                    canonical_type="canonical.order.v1",
                    source_id=replica.record_key,
                    fields={"external_id": replica.record_key},
                ),
            )
        )


class _InMemoryTransformationRepo(TransformationRepositoryPort):
    def __init__(self) -> None:
        self.items: dict[tuple[str, str, str], Transformation] = {}

    async def get_by_stream(
        self, *, tenant_id: str, connection_id: str, stream: str
    ) -> Transformation | None:
        return self.items.get((tenant_id, connection_id, stream))

    async def save(self, transformation: Transformation) -> None:
        self.items[
            (transformation.tenant_id, transformation.connection_id, transformation.stream)
        ] = transformation

    async def list_by_connection(
        self, *, tenant_id: str, connection_id: str
    ) -> list[Transformation]:
        return [
            item
            for item in self.items.values()
            if item.tenant_id == tenant_id and item.connection_id == connection_id
        ]


class _FakeControlPlaneUoW(IpControlPlaneUnitOfWorkPort):
    connections: ConnectionRepositoryPort
    entities: ConnectionEntityRepositoryPort
    sync_runs: SyncRunRepositoryPort
    transformations: _InMemoryTransformationRepo
    stitches: StitchRepositoryPort

    def __init__(self) -> None:
        self.transformations = _InMemoryTransformationRepo()
        self.commit_count = 0

    async def __aenter__(self) -> _FakeControlPlaneUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        _ = args

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        return None


class _StubDiscoverCatalogExecutor(DiscoverCatalogExecutorPort):
    def __init__(self, outcome: Result[DiscoveredCatalogDTO, IpError]) -> None:
        self._outcome = outcome

    async def execute(
        self,
        connection_id: str,
        tenant_id: str,
    ) -> Result[DiscoveredCatalogDTO, IpError]:
        _ = (connection_id, tenant_id)
        return self._outcome


@pytest.mark.asyncio
async def test_auto_bind_binds_connector_default_transformation_idempotently() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    connection_id = generate_id(IpIdPrefix.CONNECTION.value)
    uow = _FakeControlPlaneUoW()
    registry = TransformerRegistry()
    registry.register(_DefaultOrdersTransformer())

    catalog = DiscoveredCatalogDTO(
        connection_id=connection_id,
        streams=(
            StreamSchemaDTO(
                name="orders",
                fields=(),
                primary_key=("id",),
                supported_sync_modes=("INCREMENTAL",),
                default_transformation_id="canonical.orders",
                default_transformation_version=2,
            ),
            StreamSchemaDTO(
                name="raw_audit_logs",
                fields=(),
                primary_key=("id",),
                supported_sync_modes=("FULL_REFRESH",),
            ),
        ),
    )

    use_case = AutoBindDefaultTransformationOnEntitySubscribedUseCase(
        control_plane_uow=uow,
        discover_catalog_use_case=_StubDiscoverCatalogExecutor(Result.ok(catalog)),
        transformer_registry=registry,
    )

    first_res = await use_case.execute(
        AutoBindDefaultTransformationCommand(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name="orders",
        )
    )
    assert first_res.is_ok
    first_dto = first_res.unwrap()
    assert first_dto.bound is True
    assert first_dto.transformation_id == "canonical.orders"
    assert first_dto.transformation_version == 2
    assert uow.commit_count == 1

    second_res = await use_case.execute(
        AutoBindDefaultTransformationCommand(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name="orders",
        )
    )
    assert second_res.is_ok
    assert second_res.unwrap().bound is False
    assert uow.commit_count == 1

    no_default_res = await use_case.execute(
        AutoBindDefaultTransformationCommand(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name="raw_audit_logs",
        )
    )
    assert no_default_res.is_ok
    assert no_default_res.unwrap().bound is False


@pytest.mark.asyncio
async def test_auto_bind_propagates_retryable_discovery_or_missing_transformer_errors() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    connection_id = generate_id(IpIdPrefix.CONNECTION.value)
    uow = _FakeControlPlaneUoW()
    empty_registry = TransformerRegistry()

    retryable_err = UpstreamHttpError(status_code=503, message="Upstream 503")
    assert retryable_err.disposition == FailureDisposition.RETRY
    retry_uc = AutoBindDefaultTransformationOnEntitySubscribedUseCase(
        control_plane_uow=uow,
        discover_catalog_use_case=_StubDiscoverCatalogExecutor(Result.err(retryable_err)),
        transformer_registry=empty_registry,
    )
    retry_res = await retry_uc.execute(
        AutoBindDefaultTransformationCommand(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name="orders",
        )
    )
    assert retry_res.is_err
    assert retry_res.unwrap_err().code == IpErrorCode.HTTP_ERROR

    non_retry_uc = AutoBindDefaultTransformationOnEntitySubscribedUseCase(
        control_plane_uow=uow,
        discover_catalog_use_case=_StubDiscoverCatalogExecutor(
            Result.err(ConnectionNotFoundError.for_id(connection_id))
        ),
        transformer_registry=empty_registry,
    )
    skipped_res = await non_retry_uc.execute(
        AutoBindDefaultTransformationCommand(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name="orders",
        )
    )
    assert skipped_res.is_ok
    assert skipped_res.unwrap().bound is False

    unregistered_catalog = DiscoveredCatalogDTO(
        connection_id=connection_id,
        streams=(
            StreamSchemaDTO(
                name="orders",
                fields=(),
                primary_key=("id",),
                supported_sync_modes=("INCREMENTAL",),
                default_transformation_id="unregistered.transformer",
                default_transformation_version=1,
            ),
        ),
    )
    missing_xfrm_uc = AutoBindDefaultTransformationOnEntitySubscribedUseCase(
        control_plane_uow=uow,
        discover_catalog_use_case=_StubDiscoverCatalogExecutor(Result.ok(unregistered_catalog)),
        transformer_registry=empty_registry,
    )
    missing_xfrm_res = await missing_xfrm_uc.execute(
        AutoBindDefaultTransformationCommand(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name="orders",
        )
    )
    assert missing_xfrm_res.is_err
    assert missing_xfrm_res.unwrap_err().code == IpErrorCode.TRANSFORMER_NOT_FOUND
