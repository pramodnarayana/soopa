"""Narrow Integration Tests for Layer 3 Normalization Use Cases against real PostgreSQL."""

from __future__ import annotations

import pytest
from database.testing import TransactionalTestRouter
from database.types import GlobalSession, TenantSession
from ip.engine.adapters.outbound.database.control_plane.connection_repository import (
    SqlAlchemyConnectionRepository,
)
from ip.engine.adapters.outbound.database.control_plane.uow import (
    SqlAlchemyIpControlPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.data_plane.normalization_ledger_repository import (
    SqlAlchemyNormalizationLedgerRepository,
)
from ip.engine.adapters.outbound.database.data_plane.replica_record_repository import (
    SqlAlchemyReplicaRecordRepository,
)
from ip.engine.adapters.outbound.database.tenant_resolver import IpTenantResolver
from ip.engine.adapters.outbound.database.tenant_uow_provider import IpTenantUoWProvider
from ip.engine.application.use_cases.normalization.backfill_stream_normalization_use_case import (
    BackfillStreamNormalizationCommand,
    BackfillStreamNormalizationUseCase,
)
from ip.engine.application.use_cases.normalization.bind_stream_transformation_use_case import (
    BindStreamTransformationCommand,
    BindStreamTransformationUseCase,
)
from ip.engine.application.use_cases.normalization.normalize_replica_record_use_case import (
    NormalizeReplicaRecordCommand,
    NormalizeReplicaRecordUseCase,
)
from ip.engine.application.use_cases.normalization.promote_transformation_version_use_case import (
    PromoteTransformationVersionCommand,
    PromoteTransformationVersionUseCase,
)
from ip.engine.domain.enums import (
    AuthType,
    NormalizationOutcome,
    TransformationMode,
)
from ip.engine.domain.models.connection import Connection
from ip.engine.domain.models.replica_record import ReplicaRecord
from ip.engine.domain.normalization import (
    CanonicalDraft,
    CanonicalEntityDefinition,
    ReplicaSnapshot,
    TransformationContext,
    TransformationResult,
)
from ip.engine.domain.services.canonical_entity_registry import CanonicalEntityRegistry
from ip.engine.domain.services.canonical_writer_registry import (
    InMemoryCanonicalWriterRegistry,
)
from ip.engine.domain.services.default_normalization_error_policy import (
    DefaultNormalizationErrorPolicy,
)
from ip.engine.domain.services.transformer_registry import InMemoryTransformerRegistry
from ip.engine.ports.outbound.canonical_writer_port import CanonicalWriterPort
from ip.engine.ports.outbound.transformer_port import TransformerPort
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkPort
from seedwork.domain.types import JsonDict

pytestmark = pytest.mark.integration


class _RecordingCanonicalWriter(CanonicalWriterPort):
    """Test harness canonical writer recording upserts and soft-deletes during narrow DB integration tests."""

    def __init__(self, can_type: str) -> None:
        self._type = can_type
        self.rows_by_source_id: dict[str, JsonDict] = {}
        self.soft_deleted: list[str] = []

    @property
    def canonical_type(self) -> str:
        return self._type

    async def upsert(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        fields: JsonDict,
        extensions: JsonDict,
        trace_id: str,
        transformation_id: str,
        transformation_version: int,
        replica_id: str,
        replica_version: int,
        correlation_id: str | None = None,
    ) -> None:
        self.rows_by_source_id[source_id] = dict(fields)

    async def soft_delete(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        trace_id: str,
        correlation_id: str | None = None,
    ) -> None:
        self.soft_deleted.append(source_id)
        self.rows_by_source_id.pop(source_id, None)

    async def resolve_id(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
    ) -> str | None:
        if source_id in self.rows_by_source_id:
            return f"canon_{self._type}_{source_id}"
        return None

    async def resolve_reference(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        field_name: str,
        target_id: str,
        trace_id: str,
    ) -> None:
        if source_id in self.rows_by_source_id:
            self.rows_by_source_id[source_id][field_name] = target_id


class _SampleOrderTransformer(TransformerPort):
    """Pure transformer transforming replica snapshots into canonical drafts."""

    def __init__(self, version: int = 1, multiplier: float = 1.0) -> None:
        self._version = version
        self._multiplier = multiplier

    @property
    def transformation_id(self) -> str:
        return "commerce.order_mapper"

    @property
    def transformation_version(self) -> int:
        return self._version

    @property
    def target_types(self) -> tuple[str, ...]:
        return ("commerce.order",)

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult:
        raw_amount = replica.data.get("amount", 0.0)
        amount = float(raw_amount) if isinstance(raw_amount, (int, float)) else 0.0
        return TransformationResult(
            drafts=(
                CanonicalDraft(
                    canonical_type="commerce.order",
                    source_id=replica.record_key,
                    fields={"amount": amount * self._multiplier},
                ),
            )
        )


@pytest.mark.asyncio
async def test_normalization_use_cases_end_to_end_with_postgres(
    global_session: GlobalSession,
    tenant_session: TenantSession,
    transactional_router: TransactionalTestRouter,
    seeded_ip_tenant: str,
) -> None:
    # 1. Seed a Connection in Control Plane
    conn_repo = SqlAlchemyConnectionRepository(global_session)
    conn = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="erp_app",
        name="ERP Orders Connection",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://erp.example.com"},
        encrypted_credentials=b"secret",
        endpoint_for_fingerprint="https://erp.example.com",
    )
    save_res = await conn_repo.save(conn)
    assert save_res.is_ok

    # 2. Seed 3 ReplicaRecords in Data Plane
    rep_repo = SqlAlchemyReplicaRecordRepository(tenant_session)
    replicas: list[ReplicaRecord] = []
    for idx in range(1, 4):
        rep = ReplicaRecord.create(
            tenant_id=seeded_ip_tenant,
            connection_id=conn.id,
            stream="orders",
            record_key=f"ORD-{idx}",
            data={"amount": float(idx * 10)},
            trace_id=f"trc_ord_{idx}",
        )
        await rep_repo.save(rep)
        replicas.append(rep)
    await tenant_session.flush()

    # 3. Assemble registries & UoWs backed by SAVEPOINT sessions
    cp_uow = SqlAlchemyIpControlPlaneUnitOfWork(global_session)
    resolver = IpTenantResolver(db_router=transactional_router)
    dp_uow_provider = IpTenantUoWProvider(resolver=resolver, db_router=transactional_router)

    transformer_registry = InMemoryTransformerRegistry()
    transformer_registry.register(_SampleOrderTransformer(version=1, multiplier=1.0))
    transformer_registry.register(_SampleOrderTransformer(version=2, multiplier=2.0))

    writer = _RecordingCanonicalWriter("commerce.order")
    writer_registry: InMemoryCanonicalWriterRegistry[CanonicalWriterPort] = (
        InMemoryCanonicalWriterRegistry()
    )
    writer_registry.register(writer)

    entity_registry = CanonicalEntityRegistry()
    entity_registry.register(
        CanonicalEntityDefinition(
            canonical_type="commerce.order",
            schema_version=1,
        )
    )

    bind_uc = BindStreamTransformationUseCase(
        control_plane_uow=cp_uow,
        transformer_registry=transformer_registry,
    )
    promote_uc = PromoteTransformationVersionUseCase(control_plane_uow=cp_uow)
    normalize_uc = NormalizeReplicaRecordUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_uow_provider,
        transformer_registry=transformer_registry,
        writer_registry=writer_registry,
        entity_registry=entity_registry,
        error_policy=DefaultNormalizationErrorPolicy(),
    )
    backfill_uc = BackfillStreamNormalizationUseCase(
        data_plane_uow_provider=dp_uow_provider,
        normalize_use_case=normalize_uc,
    )

    # 4. Bind stream transformation (v1 active, v2 shadow)
    bind_res = await bind_uc.execute(
        BindStreamTransformationCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn.id,
            stream="orders",
            transformation_id="commerce.order_mapper",
            transformation_version=1,
            mode=TransformationMode.ACTIVE,
            shadow_transformation_version=2,
        )
    )
    assert bind_res.is_ok
    binding_dto = bind_res.unwrap()
    assert binding_dto.transformation_version == 1
    assert binding_dto.shadow_transformation_version == 2

    # 5. Normalize first replica record (verifies active write + shadow diff + ledger persistence)
    norm_res = await normalize_uc.execute(
        NormalizeReplicaRecordCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn.id,
            stream="orders",
            replica_record_id=replicas[0].id,
            replica_version=replicas[0].version,
            trace_id="trc_norm_1",
        )
    )
    assert norm_res.is_ok
    assert norm_res.unwrap().outcome == NormalizationOutcome.NORMALIZED
    assert writer.rows_by_source_id["ORD-1"] == {"amount": 10.0}

    ledger_repo = SqlAlchemyNormalizationLedgerRepository(tenant_session)
    v_recorded = await ledger_repo.get_latest_version(
        tenant_id=seeded_ip_tenant,
        replica_record_id=replicas[0].id,
        transformation_id="commerce.order_mapper",
        transformation_version=1,
    )
    assert v_recorded == 1

    # 6. Promote shadow version 2 to active
    promote_res = await promote_uc.execute(
        PromoteTransformationVersionCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn.id,
            stream="orders",
        )
    )
    assert promote_res.is_ok
    assert promote_res.unwrap().promoted_version == 2
    assert promote_res.unwrap().previous_version == 1

    # 7. Backfill stream in chunks (re-normalizes all 3 records under v2)
    backfill_res = await backfill_uc.execute(
        BackfillStreamNormalizationCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn.id,
            stream="orders",
            chunk_size=2,
            trace_id="trc_backfill",
        )
    )
    assert backfill_res.is_ok
    summary = backfill_res.unwrap()
    assert summary.processed_count == 3
    assert summary.normalized_count == 3
    assert summary.chunks_processed == 2
    assert writer.rows_by_source_id["ORD-1"] == {"amount": 20.0}
    assert writer.rows_by_source_id["ORD-2"] == {"amount": 40.0}
    assert writer.rows_by_source_id["ORD-3"] == {"amount": 60.0}
