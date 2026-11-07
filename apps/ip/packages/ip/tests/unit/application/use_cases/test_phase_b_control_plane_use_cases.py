"""Zero-mock unit tests for generic IP Engine Phase B Control Plane use cases."""

from __future__ import annotations

import contextlib
import hashlib
import os
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from datetime import timedelta
from types import TracebackType

import pytest
from database.router import DatabaseRouterPort
from database.types import GlobalSession, TenantSession
from ip.engine.adapters.outbound.stitches.stitch_adapters import (
    IpStitchCanonicalDispatcherAdapter,
)
from ip.engine.adapters.outbound.stitches.stitch_catalog_registry import (
    InMemoryStitchCatalogRegistry,
)
from ip.engine.application.use_cases.ingestion.run_sync_use_case import (
    RunSyncCommand,
    RunSyncUseCase,
)
from ip.engine.application.use_cases.ingestion.sync_run_control_plane_use_cases import (
    GetSyncRunQuery,
    GetSyncRunUseCase,
    ListStreamStatesQuery,
    ListStreamStatesUseCase,
    ListSyncRunsQuery,
    ListSyncRunsUseCase,
    ResetStreamCheckpointCommand,
    ResetStreamCheckpointUseCase,
    TriggerSyncRunCommand,
    TriggerSyncRunUseCase,
)
from ip.engine.application.use_cases.normalization.get_transformations_use_case import (
    GetStreamTransformationQuery,
    GetStreamTransformationUseCase,
    ListConnectionTransformationsQuery,
    ListConnectionTransformationsUseCase,
    ListRegisteredTransformersUseCase,
)
from ip.engine.application.use_cases.normalization.preview_stream_transformation_use_case import (
    PreviewStreamTransformationCommand,
    PreviewStreamTransformationUseCase,
)
from ip.engine.application.use_cases.stitch import (
    DispatchCanonicalEventToStitchesCommand,
    DispatchCanonicalEventToStitchesUseCase,
)
from ip.engine.application.use_cases.stitch.stitch_control_plane_use_cases import (
    GetStitchDefinitionQuery,
    GetStitchDefinitionUseCase,
    GetStitchRunQuery,
    GetStitchRunUseCase,
    ListStitchDefinitionsUseCase,
    ListStitchesQuery,
    ListStitchesUseCase,
    ListStitchRunsQuery,
    ListStitchRunsUseCase,
    RegisterStitchCommand,
    RegisterStitchUseCase,
    TriggerStitchEventCommand,
    TriggerStitchEventUseCase,
)
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.connection.enums import (
    AuthType,
    ConnectionStatus,
)
from ip.engine.domain.exceptions import (
    DuplicateConnectionFingerprintError,
    IpError,
    IpErrorCode,
    PayloadNotFoundError,
    Result,
    StitchRunNotFoundError,
    TenantShardNotFoundError,
)
from ip.engine.domain.normalization.enums import (
    NormalizationRejectionReason,
    TransformationMode,
)
from ip.engine.domain.normalization.registries import TransformerRegistry
from ip.engine.domain.normalization.transformation import (
    CanonicalDraft,
    ReplicaSnapshot,
    Transformation,
    TransformationContext,
    TransformationRejection,
    TransformationResult,
)
from ip.engine.domain.replication.enums import (
    SyncRunKind,
    SyncRunStatus,
)
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.domain.replication.stream_state import ConnectionStreamState
from ip.engine.domain.replication.sync_run import SyncRun
from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.stitch import Stitch
from ip.engine.ports.outbound.catalog_repository_port import CatalogRepositoryPort
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.connector_port import (
    AppSpecDTO,
    ConnectionCheckResultDTO,
    DiscoveredCatalogDTO,
    RecordEnvelopeDTO,
    SourceConnectorPort,
)
from ip.engine.ports.outbound.entity_map_repository_port import GlobalEntityMapRepositoryPort
from ip.engine.ports.outbound.inbound_record_repository_port import InboundRecordRepositoryPort
from ip.engine.ports.outbound.normalization_ledger_repository_port import (
    NormalizationLedgerRepositoryPort,
)
from ip.engine.ports.outbound.normalization_rejection_repository_port import (
    NormalizationRejectionRepositoryPort,
)
from ip.engine.ports.outbound.normalized_record_repository_port import (
    NormalizedRecordRepositoryPort,
)
from ip.engine.ports.outbound.outbound_record_repository_port import OutboundRecordRepositoryPort
from ip.engine.ports.outbound.pending_reference_repository_port import (
    PendingReferenceRepositoryPort,
)
from ip.engine.ports.outbound.replica_record_repository_port import ReplicaRecordRepositoryPort
from ip.engine.ports.outbound.replica_rejection_repository_port import (
    ReplicaRejectionRepositoryPort,
)
from ip.engine.ports.outbound.stitch_catalog_registry_port import StitchShardGatewayPort
from ip.engine.ports.outbound.stitch_repository_port import (
    StitchRepositoryPort,
)
from ip.engine.ports.outbound.stream_state_repository_port import (
    StreamStateRepositoryPort,
)
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort
from ip.engine.ports.outbound.tiered_storage_port import (
    TieredStoragePort,
    TieredStorageResultDTO,
)
from ip.engine.ports.outbound.transformation_repository_port import (
    TransformationRepositoryPort,
)
from ip.engine.ports.outbound.transformer_port import TransformerPort
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)
from orchestration.application.services import (
    InMemoryWorkflowDefinitionRegistry,
    WorkflowStepSchedulerService,
)
from orchestration.application.use_cases import (
    ResolveMatchConditionsUseCase,
    StartRunUseCase,
)
from orchestration.domain.constants import EffectPolicy, NodeKind, Priority, RunStatus
from orchestration.domain.definition import (
    NodeDefinition,
    WaitEventSpec,
    WorkflowDefinition,
)
from orchestration.domain.run import WorkflowRun
from orchestration.testing import InMemoryWorkflowUnitOfWork
from security.ports.cipher_port import CipherPort
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.events import EventEnvelope
from strace.ports import TraceRepositoryPort


class _SyntheticAlphaTransformerV1(TransformerPort):
    @property
    def transformation_id(self) -> str:
        return "synthetic.record_alpha"

    @property
    def transformation_version(self) -> int:
        return 1

    @property
    def target_types(self) -> tuple[str, ...]:
        return ("canonical.record_alpha.v1",)

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult:
        _ = context
        rec_id = str(replica.data.get("record_id") or replica.record_key)
        if not rec_id:
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.MISSING_REQUIRED_FIELD,
                        field_path="record_id",
                        detail="Missing record_id",
                    ),
                )
            )
        raw_amount = replica.data.get("amount", 0.0)
        amount = float(raw_amount) if isinstance(raw_amount, (int, float)) else 0.0
        return TransformationResult(
            drafts=(
                CanonicalDraft(
                    canonical_type="canonical.record_alpha.v1",
                    source_id=rec_id,
                    fields={"external_id": rec_id, "amount": amount, "tier": "STANDARD"},
                ),
            )
        )


class _SyntheticAlphaTransformerV2(TransformerPort):
    @property
    def transformation_id(self) -> str:
        return "synthetic.record_alpha"

    @property
    def transformation_version(self) -> int:
        return 2

    @property
    def target_types(self) -> tuple[str, ...]:
        return ("canonical.record_alpha.v1",)

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult:
        _ = context
        rec_id = str(replica.data.get("record_id") or replica.record_key)
        raw_amount = replica.data.get("amount", 0.0)
        amount = float(raw_amount) if isinstance(raw_amount, (int, float)) else 0.0
        return TransformationResult(
            drafts=(
                CanonicalDraft(
                    canonical_type="canonical.record_alpha.v1",
                    source_id=rec_id,
                    fields={"external_id": rec_id, "amount": amount, "tier": "ENRICHED_V2"},
                ),
            )
        )


class _SyntheticBetaTransformerV1(TransformerPort):
    @property
    def transformation_id(self) -> str:
        return "synthetic.record_beta"

    @property
    def transformation_version(self) -> int:
        return 1

    @property
    def target_types(self) -> tuple[str, ...]:
        return ("canonical.record_beta.v1",)

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult:
        _ = context
        rec_id = str(replica.data.get("beta_id") or replica.record_key)
        return TransformationResult(
            drafts=(
                CanonicalDraft(
                    canonical_type="canonical.record_beta.v1",
                    source_id=rec_id,
                    fields={"external_id": rec_id, "label": str(replica.data.get("label", ""))},
                ),
            )
        )


def _create_synthetic_transformer_registry() -> TransformerRegistry:
    registry = TransformerRegistry()
    registry.register(_SyntheticAlphaTransformerV1())
    registry.register(_SyntheticAlphaTransformerV2())
    registry.register(_SyntheticBetaTransformerV1())
    return registry


def _create_synthetic_workflow_registry() -> InMemoryWorkflowDefinitionRegistry:
    registry = InMemoryWorkflowDefinitionRegistry()
    registry.register(
        WorkflowDefinition(
            workflow_id="workflow.reconcile_alpha_stitch",
            version=1,
            default_priority=Priority.REALTIME,
            description="Synthetic three-step correlation workflow.",
            nodes=(
                NodeDefinition(
                    node_key="lookup_alpha_replica",
                    kind=NodeKind.TASK,
                    step_type=StitchStepType.QUERY_REPLICA.value,
                    effect_policy=EffectPolicy.PURE,
                ),
                NodeDefinition(
                    node_key="wait_alpha_signal",
                    kind=NodeKind.WAIT_FOR_EVENT,
                    parents=("lookup_alpha_replica",),
                    wait_event=WaitEventSpec(
                        event_key="canonical.alpha_confirmed.normalized",
                        timeout=timedelta(hours=2),
                    ),
                ),
                NodeDefinition(
                    node_key="notify_ops_sink",
                    kind=NodeKind.TASK,
                    step_type=StitchStepType.EMIT_NOTIFICATION.value,
                    parents=("wait_alpha_signal",),
                    effect_policy=EffectPolicy.IDEMPOTENT_EFFECT,
                ),
            ),
        )
    )
    registry.register(
        WorkflowDefinition(
            workflow_id="workflow.sync_alpha_to_sink_stitch",
            version=1,
            default_priority=Priority.BULK,
            description="Synthetic two-step outbound delivery workflow.",
            nodes=(
                NodeDefinition(
                    node_key="lookup_beta_context",
                    kind=NodeKind.TASK,
                    step_type=StitchStepType.QUERY_REPLICA.value,
                    effect_policy=EffectPolicy.PURE,
                ),
                NodeDefinition(
                    node_key="dispatch_sink_record",
                    kind=NodeKind.TASK,
                    step_type=StitchStepType.EXECUTE_HTTP_ACTION.value,
                    parents=("lookup_beta_context",),
                    effect_policy=EffectPolicy.RECONCILABLE_EFFECT,
                ),
            ),
        )
    )
    return registry


def _create_synthetic_stitch_catalog() -> InMemoryStitchCatalogRegistry:
    catalog = InMemoryStitchCatalogRegistry()
    catalog.register_stitch(
        Stitch(
            id="stch_default_alpha_sync",
            tenant_id="*",
            workflow_id="workflow.sync_alpha_to_sink_stitch",
            workflow_version=1,
            canonical_event_type="canonical.record_alpha.v1",
            is_trigger=True,
            idempotency_key_field="event_id",
            concurrency_key_field="external_id",
            is_active=True,
        )
    )
    catalog.register_stitch(
        Stitch(
            id="stch_default_beta_reconcile",
            tenant_id="*",
            workflow_id="workflow.reconcile_alpha_stitch",
            workflow_version=1,
            canonical_event_type="canonical.record_beta.v1",
            is_trigger=True,
            idempotency_key_field="event_id",
            concurrency_key_field="external_id",
            is_active=True,
        )
    )
    return catalog


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
        return None

    async def list_by_tenant(
        self, tenant_id: str, status: ConnectionStatus | None = None
    ) -> Sequence[Connection]:
        return [c for c in self.items.values() if c.tenant_id == tenant_id]


class _InMemoryStreamStateRepo(StreamStateRepositoryPort):
    def __init__(self) -> None:
        self.items: dict[tuple[str, str, str], ConnectionStreamState] = {}

    async def save(self, state: ConnectionStreamState) -> None:
        self.items[(state.tenant_id, state.connection_id, state.stream_name)] = state

    async def get_by_stream(
        self, tenant_id: str, connection_id: str, stream_name: str
    ) -> ConnectionStreamState | None:
        return self.items.get((tenant_id, connection_id, stream_name))

    async def list_by_connection(
        self, tenant_id: str, connection_id: str
    ) -> Sequence[ConnectionStreamState]:
        return [
            s
            for s in self.items.values()
            if s.tenant_id == tenant_id and s.connection_id == connection_id
        ]


class _InMemorySyncRunRepo(SyncRunRepositoryPort):
    def __init__(self) -> None:
        self.items: dict[str, SyncRun] = {}

    async def save(self, run: SyncRun) -> None:
        self.items[run.id] = run

    async def get_by_id(self, run_id: str, tenant_id: str) -> SyncRun | None:
        r = self.items.get(run_id)
        return r if r is not None and r.tenant_id == tenant_id else None

    async def get_active_run(
        self,
        connection_id: str,
        stream: str,
        tenant_id: str | None = None,
        for_update: bool = False,
    ) -> SyncRun | None:
        for r in self.items.values():
            if (
                (tenant_id is None or r.tenant_id == tenant_id)
                and r.connection_id == connection_id
                and r.stream == stream
                and r.status in (SyncRunStatus.PENDING, SyncRunStatus.RUNNING)
            ):
                return r
        return None

    async def get_latest_generation_id(
        self, tenant_id: str, connection_id: str, stream: str
    ) -> int:
        gen = 1
        for r in self.items.values():
            if r.tenant_id == tenant_id and r.connection_id == connection_id and r.stream == stream:
                gen = max(gen, r.generation_id)
        return gen

    async def list_by_connection(
        self,
        tenant_id: str,
        connection_id: str,
        limit: int = 50,
    ) -> Sequence[SyncRun]:
        return [
            r
            for r in self.items.values()
            if r.tenant_id == tenant_id and r.connection_id == connection_id
        ][:limit]


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
            b
            for b in self.items.values()
            if b.tenant_id == tenant_id and b.connection_id == connection_id
        ]


class _InMemoryStitchRepo(StitchRepositoryPort):
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], Stitch] = {}

    async def save(self, stitch: Stitch) -> None:
        self.items[(stitch.id, stitch.tenant_id)] = stitch

    async def get_by_id(self, *, tenant_id: str, stitch_id: str) -> Stitch | None:
        sub = self.items.get((stitch_id, tenant_id))
        if sub is not None:
            return sub
        return self.items.get((stitch_id, "*"))

    async def get_by_id_global(self, *, stitch_id: str) -> Stitch | None:
        for (sid, tid), stitch in self.items.items():
            if sid == stitch_id and tid != "*":
                return stitch
        for (sid, tid), stitch in self.items.items():
            if sid == stitch_id and tid == "*":
                return stitch
        return None

    async def list_by_tenant(self, *, tenant_id: str) -> list[Stitch]:
        matching = [s for s in self.items.values() if s.tenant_id in (tenant_id, "*")]
        by_id: dict[str, Stitch] = {}
        for s in matching:
            if s.id not in by_id or s.tenant_id == tenant_id:
                by_id[s.id] = s
        return list(by_id.values())

    async def list_for_event(self, *, tenant_id: str, canonical_event_type: str) -> list[Stitch]:
        matching = [
            s
            for s in self.items.values()
            if s.tenant_id in (tenant_id, "*")
            and s.canonical_event_type == canonical_event_type
            and s.is_active
        ]
        by_id: dict[str, Stitch] = {}
        for s in matching:
            if s.id not in by_id or s.tenant_id == tenant_id:
                by_id[s.id] = s
        return list(by_id.values())


class _InMemoryControlPlaneUoW(IpControlPlaneUnitOfWorkPort):
    connections: ConnectionRepositoryPort
    catalogs: CatalogRepositoryPort
    stream_states: StreamStateRepositoryPort
    sync_runs: SyncRunRepositoryPort
    transformations: TransformationRepositoryPort
    stitches: StitchRepositoryPort

    def __init__(self) -> None:
        self.connections = _InMemoryConnectionRepo()
        self.stream_states = _InMemoryStreamStateRepo()
        self.sync_runs = _InMemorySyncRunRepo()
        self.transformations = _InMemoryTransformationRepo()
        self.stitches = _InMemoryStitchRepo()
        self.committed = False

    async def __aenter__(self) -> _InMemoryControlPlaneUoW:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass

    async def record_idempotency(self, tenant_id: str, idempotency_key: str) -> bool:
        _ = (tenant_id, idempotency_key)
        return True

    async def release_idempotency(self, tenant_id: str, idempotency_key: str) -> None:
        _ = (tenant_id, idempotency_key)

    async def stage_outbox_envelope(self, envelope: EventEnvelope) -> None:
        _ = envelope


class _InMemoryInboundRecordRepository(InboundRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[str, InboundRecord] = {}

    async def save(self, record: InboundRecord) -> None:
        self.records[record.id] = record

    async def get_by_id(self, record_id: str, tenant_id: str) -> InboundRecord | None:
        rec = self.records.get(record_id)
        return rec if rec and rec.tenant_id == tenant_id else None

    async def get_by_trace_id(
        self,
        trace_id: str,
        tenant_id: str,
        *,
        hydrate_payloads: bool = False,
    ) -> Sequence[InboundRecord]:
        return [
            r for r in self.records.values() if r.trace_id == trace_id and r.tenant_id == tenant_id
        ]

    async def get_by_external_event_id(
        self, tenant_id: str, connection_id: str, external_event_id: str
    ) -> InboundRecord | None:
        return None


class _InMemoryDataPlaneUoW(IpDataPlaneUnitOfWorkPort):
    inbound_records: InboundRecordRepositoryPort
    replica_records: ReplicaRecordRepositoryPort
    replica_rejections: ReplicaRejectionRepositoryPort
    normalized_records: NormalizedRecordRepositoryPort
    entity_maps: GlobalEntityMapRepositoryPort
    outbound_records: OutboundRecordRepositoryPort
    normalization_ledger: NormalizationLedgerRepositoryPort
    normalization_rejections: NormalizationRejectionRepositoryPort
    pending_references: PendingReferenceRepositoryPort
    traces: TraceRepositoryPort

    def __init__(self) -> None:
        self.inbound_records = _InMemoryInboundRecordRepository()
        self.committed = False

    async def __aenter__(self) -> _InMemoryDataPlaneUoW:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass

    async def record_idempotency(self, tenant_id: str, idempotency_key: str) -> bool:
        _ = (tenant_id, idempotency_key)
        return True

    async def release_idempotency(self, tenant_id: str, idempotency_key: str) -> None:
        _ = (tenant_id, idempotency_key)

    async def stage_outbox_envelope(self, envelope: EventEnvelope) -> None:
        _ = envelope


class _InMemoryCipher(CipherPort):
    def encrypt_str(self, text: str) -> str:
        return "enc_" + text

    def decrypt_str(self, ciphertext: str) -> str:
        return ciphertext.removeprefix("enc_")

    def encrypt_dict(self, data: JsonDict) -> bytes:
        return b"encrypted"

    def decrypt_dict(self, encrypted_bytes: bytes) -> JsonDict:
        return {}


class _InMemoryTieredStorage(TieredStoragePort):
    async def store(
        self,
        tenant_id: str,
        trace_id: str,
        payload_bytes: bytes,
        parsed_payload: JsonValue | None = None,
    ) -> TieredStorageResultDTO:
        return TieredStorageResultDTO(
            is_inlined=True,
            raw_payload=parsed_payload if isinstance(parsed_payload, dict) else None,
            s3_key=None,
            payload_size_bytes=len(payload_bytes),
            payload_sha256=hashlib.sha256(payload_bytes).hexdigest(),
        )

    async def retrieve(self, result: TieredStorageResultDTO) -> Result[bytes, PayloadNotFoundError]:
        return Result.ok(b"")


class _InMemoryPagingConnector(SourceConnectorPort):
    def __init__(self, record_batches: list[list[JsonDict]]) -> None:
        self._record_batches = record_batches

    @property
    def app_id(self) -> str:
        return "acme_source"

    def spec(self) -> AppSpecDTO:
        raise NotImplementedError

    async def check(
        self, public_config: JsonDict, credentials: JsonDict
    ) -> ConnectionCheckResultDTO:
        raise NotImplementedError

    async def discover(
        self, connection_id: str, public_config: JsonDict, credentials: JsonDict
    ) -> DiscoveredCatalogDTO:
        raise NotImplementedError

    async def list_objects(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Sequence[str]:
        return []

    async def read_stream(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        cursor: str | None = None,
        limit: int = 100,
    ) -> AsyncIterator[RecordEnvelopeDTO]:
        for batch in self._record_batches:
            for item in batch:
                yield RecordEnvelopeDTO(
                    stream_name=stream_name,
                    record_id=str(item.get("id", "")),
                    data=item,
                    emitted_at="2026-10-23T10:00:00Z",
                    cursor_value=str(item.get("timestamp")),
                )

    async def fetch_record(
        self,
        stream_name: str,
        record_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> RecordEnvelopeDTO | None:
        return None


class _InMemoryStitchShardGateway(StitchShardGatewayPort):
    def __init__(
        self,
        wf_uow: InMemoryWorkflowUnitOfWork,
        dispatcher: DispatchCanonicalEventToStitchesUseCase,
    ) -> None:
        self._wf_uow = wf_uow
        self._dispatcher = dispatcher

    async def dispatch_event(
        self,
        *,
        tenant_id: str,
        canonical_event_type: str,
        event_id: str,
        payload: JsonDict,
        trace_id: str,
        correlation_id: str | None = None,
    ) -> Result[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]], IpError]:
        res = await self._dispatcher.execute(
            DispatchCanonicalEventToStitchesCommand(
                tenant_id=tenant_id,
                canonical_event_type=canonical_event_type,
                event_id=event_id,
                payload=payload,
                trace_id=trace_id,
                correlation_id=correlation_id,
            )
        )
        if res.is_err:
            err = res.unwrap_err()
            return Result.err(
                IpError(
                    code=IpErrorCode.INTERNAL_ERROR,
                    message=err.message,
                )
            )
        dto = res.unwrap()
        return Result.ok(
            (
                dto.started_run_ids,
                dto.deduplicated_run_ids,
                dto.signalled_step_ids,
            )
        )

    async def get_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
    ) -> Result[WorkflowRun, IpError]:
        run_res = await self._wf_uow.runs.get_by_id(tenant_id, run_id)
        if run_res.is_err:
            return Result.err(StitchRunNotFoundError.for_id(run_id))
        return Result.ok(run_res.unwrap())

    async def list_runs(
        self,
        *,
        tenant_id: str,
        workflow_id: str | None = None,
        status: RunStatus | None = None,
        limit: int = 50,
    ) -> Result[tuple[WorkflowRun, ...], IpError]:
        runs = await self._wf_uow.runs.list_recent(
            tenant_id,
            workflow_id=workflow_id,
            status=status,
            limit=limit,
        )
        return Result.ok(tuple(runs))


@pytest.mark.asyncio
async def test_transformation_preview_use_case_with_shadow_diff_comparison() -> None:
    registry = _create_synthetic_transformer_registry()
    list_transformers_uc = ListRegisteredTransformersUseCase(transformer_registry=registry)
    transformers = list_transformers_uc.execute()
    assert len(transformers) == 3
    transformer_keys = {(m.transformation_id, m.transformation_version) for m in transformers}
    assert ("synthetic.record_alpha", 1) in transformer_keys
    assert ("synthetic.record_alpha", 2) in transformer_keys
    assert ("synthetic.record_beta", 1) in transformer_keys

    preview_uc = PreviewStreamTransformationUseCase(transformer_registry=registry)
    alpha_preview = preview_uc.execute(
        PreviewStreamTransformationCommand(
            tenant_id="ten_01",
            connection_id="conn_01",
            stream="records_alpha",
            transformation_id="synthetic.record_alpha",
            transformation_version=1,
            record_key="REC-100",
            sample_payload={
                "record_id": "REC-100",
                "amount": 120.5,
                "timestamp": "2026-10-27T10:00:00Z",
            },
            shadow_transformation_version=2,
        )
    )
    assert alpha_preview.is_ok
    dto = alpha_preview.unwrap()
    assert len(dto.drafts) == 1
    assert dto.drafts[0].source_id == "REC-100"
    assert dto.shadow_transformation_version == 2
    assert len(dto.shadow_diffs) >= 1

    beta_preview = preview_uc.execute(
        PreviewStreamTransformationCommand(
            tenant_id="ten_01",
            connection_id="conn_01",
            stream="records_beta",
            transformation_id="synthetic.record_beta",
            transformation_version=1,
            record_key="BETA-01",
            sample_payload={"beta_id": "BETA-01", "label": "Primary Sink"},
        )
    )
    assert beta_preview.is_ok
    assert len(beta_preview.unwrap().drafts) == 1

    rejected_preview = preview_uc.execute(
        PreviewStreamTransformationCommand(
            tenant_id="ten_01",
            connection_id="conn_01",
            stream="records_alpha",
            transformation_id="synthetic.record_alpha",
            transformation_version=1,
            record_key="",
            sample_payload={"amount": 10.0},
        )
    )
    assert rejected_preview.is_ok
    assert len(rejected_preview.unwrap().rejections) == 1

    missing_transformer = preview_uc.execute(
        PreviewStreamTransformationCommand(
            tenant_id="ten_01",
            connection_id="conn_01",
            stream="records_alpha",
            transformation_id="unknown.transformer",
            transformation_version=99,
            record_key="REC-100",
            sample_payload={},
        )
    )
    assert missing_transformer.is_err
    assert missing_transformer.unwrap_err().code == IpErrorCode.TRANSFORMER_NOT_FOUND


@pytest.mark.asyncio
async def test_connection_transformation_query_use_cases() -> None:
    uow = _InMemoryControlPlaneUoW()
    conn = Connection(
        id="conn_01",
        tenant_id="ten_01",
        app_id="acme_source",
        name="Acme Source Connection",
        auth_type=AuthType.API_KEY,
        connection_fingerprint="fp_01",
        status=ConnectionStatus.ACTIVE,
    )
    await uow.connections.save(conn)
    transformation = Transformation.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="records_alpha",
        transformation_id="synthetic.record_alpha",
        transformation_version=1,
        mode=TransformationMode.ACTIVE,
        shadow_transformation_version=2,
    )
    await uow.transformations.save(transformation)

    list_transformations_uc = ListConnectionTransformationsUseCase(control_plane_uow=uow)
    transformations_res = await list_transformations_uc.execute(
        ListConnectionTransformationsQuery(tenant_id="ten_01", connection_id="conn_01")
    )
    assert transformations_res.is_ok
    assert len(transformations_res.unwrap()) == 1

    missing_conn_res = await list_transformations_uc.execute(
        ListConnectionTransformationsQuery(tenant_id="ten_01", connection_id="conn_missing")
    )
    assert missing_conn_res.is_err
    assert missing_conn_res.unwrap_err().code == IpErrorCode.CONNECTION_NOT_FOUND

    get_transformation_uc = GetStreamTransformationUseCase(control_plane_uow=uow)
    get_res = await get_transformation_uc.execute(
        GetStreamTransformationQuery(
            tenant_id="ten_01",
            connection_id="conn_01",
            stream="records_alpha",
        )
    )
    assert get_res.is_ok
    assert get_res.unwrap().id == transformation.id

    missing_stream_res = await get_transformation_uc.execute(
        GetStreamTransformationQuery(
            tenant_id="ten_01",
            connection_id="conn_01",
            stream="unmapped_stream",
        )
    )
    assert missing_stream_res.is_err
    assert missing_stream_res.unwrap_err().code == IpErrorCode.TRANSFORMATION_NOT_FOUND


@pytest.mark.asyncio
async def test_sync_run_control_plane_lifecycle_resumes_pending_run() -> None:
    cp_uow = _InMemoryControlPlaneUoW()
    dp_uow = _InMemoryDataPlaneUoW()
    conn = Connection(
        id="conn_sync_01",
        tenant_id="ten_01",
        app_id="acme_source",
        name="Acme Pull Connection",
        auth_type=AuthType.API_KEY,
        connection_fingerprint="fp_sync_01",
        status=ConnectionStatus.ACTIVE,
    )
    await cp_uow.connections.save(conn)

    trigger_uc = TriggerSyncRunUseCase(control_plane_uow=cp_uow)
    trigger_res = await trigger_uc.execute(
        TriggerSyncRunCommand(
            tenant_id="ten_01",
            connection_id="conn_sync_01",
            stream_name="records_alpha",
            correlation_id="corr_sync_01",
        )
    )
    assert trigger_res.is_ok
    queued_dto = trigger_res.unwrap()
    assert queued_dto.status == SyncRunStatus.PENDING.value
    assert queued_dto.kind == SyncRunKind.INITIAL.value
    assert queued_dto.generation_id == 1

    conflict_res = await trigger_uc.execute(
        TriggerSyncRunCommand(
            tenant_id="ten_01",
            connection_id="conn_sync_01",
            stream_name="records_alpha",
        )
    )
    assert conflict_res.is_err
    assert conflict_res.unwrap_err().code == IpErrorCode.ACTIVE_SYNC_RUN_EXISTS

    connector = _InMemoryPagingConnector([[{"id": "rec_01", "timestamp": "2026-10-27T11:00:00Z"}]])
    run_sync_uc = RunSyncUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=_InMemoryTieredStorage(),
        cipher=_InMemoryCipher(),
        connectors={"acme_source": connector},
    )
    exec_res = await run_sync_uc.execute(
        RunSyncCommand(
            tenant_id="ten_01",
            connection_id="conn_sync_01",
            stream_name="records_alpha",
            trace_id=queued_dto.trace_id,
        )
    )
    assert exec_res.run_id == queued_dto.run_id
    assert exec_res.status == SyncRunStatus.SUCCEEDED.value
    assert exec_res.records_synced == 1

    list_runs_uc = ListSyncRunsUseCase(control_plane_uow=cp_uow)
    runs_res = await list_runs_uc.execute(
        ListSyncRunsQuery(tenant_id="ten_01", connection_id="conn_sync_01")
    )
    assert runs_res.is_ok
    assert len(runs_res.unwrap()) == 1

    get_run_uc = GetSyncRunUseCase(control_plane_uow=cp_uow)
    get_run_res = await get_run_uc.execute(
        GetSyncRunQuery(
            tenant_id="ten_01",
            connection_id="conn_sync_01",
            run_id=queued_dto.run_id,
        )
    )
    assert get_run_res.is_ok
    assert get_run_res.unwrap().status == SyncRunStatus.SUCCEEDED.value

    missing_run_res = await get_run_uc.execute(
        GetSyncRunQuery(
            tenant_id="ten_01",
            connection_id="conn_sync_01",
            run_id="ip_sync_missing",
        )
    )
    assert missing_run_res.is_err
    assert missing_run_res.unwrap_err().code == IpErrorCode.SYNC_RUN_NOT_FOUND

    list_states_uc = ListStreamStatesUseCase(control_plane_uow=cp_uow)
    states_res = await list_states_uc.execute(
        ListStreamStatesQuery(tenant_id="ten_01", connection_id="conn_sync_01")
    )
    assert states_res.is_ok
    assert len(states_res.unwrap()) == 1
    assert states_res.unwrap()[0].cursor_value == "2026-10-27T11:00:00Z"

    reset_uc = ResetStreamCheckpointUseCase(control_plane_uow=cp_uow)
    reset_res = await reset_uc.execute(
        ResetStreamCheckpointCommand(
            tenant_id="ten_01",
            connection_id="conn_sync_01",
            stream_name="records_alpha",
        )
    )
    assert reset_res.is_ok
    assert reset_res.unwrap().cursor_value is None


@pytest.mark.asyncio
async def test_stitch_control_plane_use_cases() -> None:
    wf_reg = _create_synthetic_workflow_registry()
    stitch_cat = _create_synthetic_stitch_catalog()

    list_defs_uc = ListStitchDefinitionsUseCase(definition_registry=wf_reg)
    defs = list_defs_uc.execute()
    assert len(defs) == 2

    get_def_uc = GetStitchDefinitionUseCase(definition_registry=wf_reg)
    def_res = get_def_uc.execute(
        GetStitchDefinitionQuery(workflow_id="workflow.reconcile_alpha_stitch")
    )
    assert def_res.is_ok
    assert def_res.unwrap().workflow_id == "workflow.reconcile_alpha_stitch"
    assert len(def_res.unwrap().nodes) == 3

    missing_def_res = get_def_uc.execute(GetStitchDefinitionQuery(workflow_id="unknown.stitch"))
    assert missing_def_res.is_err
    assert missing_def_res.unwrap_err().code == IpErrorCode.STITCH_DEFINITION_NOT_FOUND

    tenant_id = f"ten_{os.urandom(12).hex()}"
    other_tenant_id = f"ten_{os.urandom(12).hex()}"
    custom_stitch_id = f"stitch_{os.urandom(12).hex()}"
    shared_stitch_id = f"stitch_{os.urandom(12).hex()}"
    bad_stitch_id = f"stitch_{os.urandom(12).hex()}"
    missing_run_id = f"wfr_{os.urandom(12).hex()}"

    cp_uow = _InMemoryControlPlaneUoW()
    list_stitches_uc = ListStitchesUseCase(
        stitch_catalog=stitch_cat,
        uow=cp_uow,
    )
    stitches = await list_stitches_uc.execute(ListStitchesQuery(tenant_id=tenant_id))
    assert len(stitches) >= 2

    reg_stitch_uc = RegisterStitchUseCase(
        stitch_catalog=stitch_cat,
        definition_registry=wf_reg,
        uow=cp_uow,
    )
    reg_res = await reg_stitch_uc.execute(
        RegisterStitchCommand(
            tenant_id=tenant_id,
            stitch_id=custom_stitch_id,
            workflow_id="workflow.sync_alpha_to_sink_stitch",
            workflow_version=1,
            canonical_event_type="canonical.custom_alpha.normalized",
            is_trigger=True,
            idempotency_key_field="external_id",
        )
    )
    assert reg_res.is_ok
    assert reg_res.unwrap().id == custom_stitch_id

    reg_wildcard = await reg_stitch_uc.execute(
        RegisterStitchCommand(
            tenant_id="*",
            stitch_id=shared_stitch_id,
            workflow_id="workflow.sync_alpha_to_sink_stitch",
            workflow_version=1,
            canonical_event_type="canonical.custom_alpha.normalized",
            is_trigger=True,
        )
    )
    assert reg_wildcard.is_ok

    reg_override = await reg_stitch_uc.execute(
        RegisterStitchCommand(
            tenant_id=tenant_id,
            stitch_id=shared_stitch_id,
            workflow_id="workflow.sync_alpha_to_sink_stitch",
            workflow_version=1,
            canonical_event_type="canonical.custom_alpha.normalized",
            is_trigger=True,
        )
    )
    assert reg_override.is_ok

    reg_conflict = await reg_stitch_uc.execute(
        RegisterStitchCommand(
            tenant_id=other_tenant_id,
            stitch_id=shared_stitch_id,
            workflow_id="workflow.sync_alpha_to_sink_stitch",
            workflow_version=1,
            canonical_event_type="canonical.custom_alpha.normalized",
            is_trigger=True,
        )
    )
    assert reg_conflict.is_err
    assert reg_conflict.unwrap_err().http_status == 409

    matching_stitches = stitch_cat.list_stitches_for_event(
        tenant_id=tenant_id,
        canonical_event_type="canonical.custom_alpha.normalized",
    )
    matching_ids = [s.id for s in matching_stitches]
    assert matching_ids.count(shared_stitch_id) == 1
    overridden = next(s for s in matching_stitches if s.id == shared_stitch_id)
    assert overridden.tenant_id == tenant_id

    stitch_cat.register_stitch(
        Stitch(
            id=shared_stitch_id,
            tenant_id=tenant_id,
            workflow_id="workflow.sync_alpha_to_sink_stitch",
            workflow_version=1,
            canonical_event_type="canonical.custom_alpha.normalized",
            is_trigger=True,
            is_active=False,
        )
    )
    inactive_override_matches = stitch_cat.list_stitches_for_event(
        tenant_id=tenant_id,
        canonical_event_type="canonical.custom_alpha.normalized",
    )
    assert not any(s.id == shared_stitch_id for s in inactive_override_matches)

    bad_reg_res = await reg_stitch_uc.execute(
        RegisterStitchCommand(
            tenant_id=tenant_id,
            stitch_id=bad_stitch_id,
            workflow_id="nonexistent.workflow",
            workflow_version=1,
            canonical_event_type="canonical.event",
            is_trigger=True,
        )
    )
    assert bad_reg_res.is_err
    assert bad_reg_res.unwrap_err().code == IpErrorCode.STITCH_DEFINITION_NOT_FOUND

    wf_uow = InMemoryWorkflowUnitOfWork()
    scheduler = WorkflowStepSchedulerService()
    match_resolver = ResolveMatchConditionsUseCase(
        uow_factory=lambda: wf_uow,
        definition_registry=wf_reg,
        step_scheduler=scheduler,
    )
    start_run = StartRunUseCase(
        uow_factory=lambda: wf_uow,
        definition_registry=wf_reg,
        step_scheduler=scheduler,
    )
    dispatcher = DispatchCanonicalEventToStitchesUseCase(
        stitch_catalog=stitch_cat,
        start_run_use_case=start_run,
        resolve_matches_use_case=match_resolver,
    )
    shard_gw = _InMemoryStitchShardGateway(wf_uow, dispatcher)

    trigger_stitch_uc = TriggerStitchEventUseCase(shard_gateway=shard_gw)
    disp_res = await trigger_stitch_uc.execute(
        TriggerStitchEventCommand(
            tenant_id=tenant_id,
            canonical_event_type="canonical.record_alpha.v1",
            payload={
                "source_id": "REC-777",
                "external_id": "REC-777",
                "amount": 88.2,
            },
            correlation_id="REC-777",
        )
    )
    assert disp_res.is_ok
    started_run_ids = disp_res.unwrap().started_run_ids
    assert len(started_run_ids) == 1
    run_id = started_run_ids[0]

    get_stitch_run_uc = GetStitchRunUseCase(shard_gateway=shard_gw)
    run_res = await get_stitch_run_uc.execute(GetStitchRunQuery(tenant_id=tenant_id, run_id=run_id))
    assert run_res.is_ok
    run_dto = run_res.unwrap()
    assert run_dto.run_id == run_id
    assert run_dto.workflow_id == "workflow.sync_alpha_to_sink_stitch"
    assert len(run_dto.steps) == 2

    missing_stitch_run = await get_stitch_run_uc.execute(
        GetStitchRunQuery(tenant_id=tenant_id, run_id=missing_run_id)
    )
    assert missing_stitch_run.is_err
    assert missing_stitch_run.unwrap_err().code == IpErrorCode.STITCH_RUN_NOT_FOUND

    list_runs_uc = ListStitchRunsUseCase(shard_gateway=shard_gw)
    listed_runs_res = await list_runs_uc.execute(
        ListStitchRunsQuery(
            tenant_id=tenant_id,
            workflow_id="workflow.sync_alpha_to_sink_stitch",
            status=RunStatus(run_dto.status),
            limit=20,
        )
    )
    assert listed_runs_res.is_ok
    listed_runs = listed_runs_res.unwrap()
    assert len(listed_runs) == 1
    assert listed_runs[0].run_id == run_id


class _EmptySessionDbRouter(DatabaseRouterPort):
    async def get_global_session(self) -> AsyncGenerator[GlobalSession, None]:
        for _ in ():
            yield _

    async def get_tenant_session(
        self, tenant_id: str, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        _ = (tenant_id, shard_key, shard_url)
        for _ in ():
            yield _

    async def get_shard_session(
        self, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        _ = (shard_key, shard_url)
        for _ in ():
            yield _

    async def get_all_shards(self, app_slug: str | None = None) -> list[tuple[str, str]]:
        _ = app_slug
        return []

    async def close_all(self) -> None:
        return None


class _StaticDpUowProvider(IpDataPlaneUnitOfWorkProviderPort):
    def __init__(self, *, missing_tenant_id: str) -> None:
        self._missing_tenant_id = missing_tenant_id

    async def resolve_shard_info(
        self, target_tenant_id: str
    ) -> Result[tuple[str, str], TenantShardNotFoundError]:
        if target_tenant_id == self._missing_tenant_id:
            return Result.err(TenantShardNotFoundError.for_tenant(target_tenant_id))
        return Result.ok(("shard-01", "postgresql+asyncpg://localhost/shard01"))

    @contextlib.asynccontextmanager
    async def get_data_plane_uow(
        self,
        target_tenant_id: str,
        shard_id: str,
        shard_dsn: str,
    ) -> AsyncIterator[IpDataPlaneUnitOfWorkPort]:
        _ = (target_tenant_id, shard_id, shard_dsn)
        raise AssertionError("get_data_plane_uow should not be invoked by list_runs")
        yield  # unreachable generator marker


@pytest.mark.asyncio
async def test_stitch_dispatcher_adapter_list_runs_returns_shard_not_found_errors() -> None:
    wf_reg = _create_synthetic_workflow_registry()
    stitch_cat = _create_synthetic_stitch_catalog()
    wf_uow = InMemoryWorkflowUnitOfWork()
    tenant_id = f"ten_{os.urandom(12).hex()}"
    missing_tenant_id = f"ten_{os.urandom(12).hex()}"

    empty_session_adapter = IpStitchCanonicalDispatcherAdapter(
        db_router=_EmptySessionDbRouter(),
        dp_uow_provider=_StaticDpUowProvider(missing_tenant_id=missing_tenant_id),
        stitch_catalog=stitch_cat,
        definition_registry=wf_reg,
        workflow_uow_factory=lambda _session: wf_uow,
    )

    missing_shard_res = await empty_session_adapter.list_runs(tenant_id=missing_tenant_id)
    assert missing_shard_res.is_err
    assert missing_shard_res.unwrap_err().code == IpErrorCode.TENANT_SHARD_NOT_FOUND

    empty_session_res = await empty_session_adapter.list_runs(
        tenant_id=tenant_id,
        status=RunStatus.RUNNING,
    )
    assert empty_session_res.is_err
    assert empty_session_res.unwrap_err().code == IpErrorCode.TENANT_SHARD_NOT_FOUND
