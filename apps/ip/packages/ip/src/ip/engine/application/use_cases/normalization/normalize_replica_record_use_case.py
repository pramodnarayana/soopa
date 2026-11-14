"""Universal Layer 3 Canonical Normalization Use Case.

Orchestrates transforming Layer 2 Replica snapshots into Layer 3 Canonical domain entities
with idempotency version guards, tombstone cascade soft-deletes, differential reconciliation,
quality rules evaluation, reference resolution/back-patching, and shadow mode comparison
without raising exceptions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

import structlog
from seedwork.domain.types import JsonDict
from structlog.typing import FilteringBoundLogger

from ip.engine.domain.dispatch.enums import FailureDisposition
from ip.engine.domain.exceptions import (
    IpError,
    NormalizationFailedError,
    ReplicaRecordNotFoundError,
    Result,
)
from ip.engine.domain.normalization.enums import (
    NormalizationOutcome,
    NormalizationRejectionReason,
    RuleSeverity,
    TransformationMode,
)
from ip.engine.domain.normalization.event_policies import STANDALONE_OUTBOX_EVENT_POLICY
from ip.engine.domain.normalization.events import CanonicalRecordChangedEvent
from ip.engine.domain.normalization.ledger import (
    EntityShadowDiff,
    FieldShadowDiff,
    NormalizationLedgerEntry,
    NormalizationRejectionEntry,
    NormalizationShadowDiffEntry,
    PendingReferenceEntry,
)
from ip.engine.domain.normalization.transformation import (
    CanonicalDraft,
    ReplicaSnapshot,
    Transformation,
    TransformationContext,
    TransformationResult,
)
from ip.engine.domain.replication.replica_record import ReplicaRecord
from ip.engine.ports.outbound.canonical_writer_port import (
    CanonicalEntityRegistryPort,
    CanonicalWriterRegistryPort,
)
from ip.engine.ports.outbound.normalization_error_policy_port import (
    NormalizationErrorPolicyPort,
)
from ip.engine.ports.outbound.pipeline_event_policy_port import (
    NormalizationEventPolicyPort,
)
from ip.engine.ports.outbound.transformer_port import (
    TransformerPort,
    TransformerRegistryPort,
)
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class NormalizeReplicaRecordCommand:
    """Command triggering universal normalization for an extracted replica record."""

    tenant_id: str
    connection_id: str
    stream: str
    replica_record_id: str
    replica_version: int
    trace_id: str
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0


@dataclass(frozen=True)
class NormalizeReplicaRecordResultDTO:
    """Result payload from the universal normalization engine."""

    outcome: NormalizationOutcome
    canonical_refs_produced: tuple[tuple[str, str], ...] = ()
    canonical_events: tuple[CanonicalRecordChangedEvent, ...] = ()
    rejections_count: int = 0
    shadow_diff_count: int = 0
    resolved_references_count: int = 0
    error_detail: str | None = None
    canonical_payloads: Mapping[tuple[str, str], JsonDict] = field(default_factory=dict)


class _RejectionPersistenceStrategy(Protocol):
    """Strategy governing how terminal transformer rejections are persisted per execution mode."""

    async def record_terminal_rejection(
        self,
        *,
        uow: IpDataPlaneUnitOfWorkPort,
        command: NormalizeReplicaRecordCommand,
        transformation: Transformation,
        rejection: NormalizationRejectionEntry,
        detail: str,
        summary_message: str,
    ) -> None: ...


class _ActiveLedgerRejectionStrategy:
    """Persists both the rejection entry and a terminal NormalizationLedgerEntry."""

    async def record_terminal_rejection(
        self,
        *,
        uow: IpDataPlaneUnitOfWorkPort,
        command: NormalizeReplicaRecordCommand,
        transformation: Transformation,
        rejection: NormalizationRejectionEntry,
        detail: str,
        summary_message: str,
    ) -> None:
        await uow.normalization_rejections.record_rejection(rejection)
        rejected_ledger = NormalizationLedgerEntry.reject_execution(
            tenant_id=command.tenant_id,
            replica_record_id=command.replica_record_id,
            replica_version=command.replica_version,
            transformation_id=transformation.transformation_id,
            transformation_version=transformation.transformation_version,
            reason_code=NormalizationRejectionReason.TRANSFORMER_ERROR.value,
            detail=detail,
            summary_message=summary_message,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            parent_trace_id=command.parent_trace_id,
            original_trace_id=command.original_trace_id,
            replay_count=command.replay_count,
        )
        await uow.normalization_ledger.record_entry(rejected_ledger)


class _ShadowTraceRejectionStrategy:
    """Persists the rejection entry and trace event without mutating the active ledger."""

    async def record_terminal_rejection(
        self,
        *,
        uow: IpDataPlaneUnitOfWorkPort,
        command: NormalizeReplicaRecordCommand,
        transformation: Transformation,
        rejection: NormalizationRejectionEntry,
        detail: str,
        summary_message: str,
    ) -> None:
        await uow.normalization_rejections.record_rejection(rejection)
        await uow.traces.save_trace_event(
            rejection.build_rejection_trace(summary_message=summary_message)
        )


_ACTIVE_REJECTION_STRATEGY = _ActiveLedgerRejectionStrategy()
_SHADOW_REJECTION_STRATEGY = _ShadowTraceRejectionStrategy()


class NormalizeReplicaRecordUseCase:
    """Universal Layer 3 normalization orchestrator."""

    def __init__(
        self,
        control_plane_uow: IpControlPlaneUnitOfWorkPort,
        data_plane_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        transformer_registry: TransformerRegistryPort,
        writer_registry: CanonicalWriterRegistryPort,
        entity_registry: CanonicalEntityRegistryPort,
        error_policy: NormalizationErrorPolicyPort,
    ) -> None:
        self._control_plane_uow = control_plane_uow
        self._data_plane_uow_provider = data_plane_uow_provider
        self._transformer_registry = transformer_registry
        self._writer_registry = writer_registry
        self._entity_registry = entity_registry
        self._error_policy = error_policy

    async def execute(
        self,
        command: NormalizeReplicaRecordCommand,
    ) -> Result[NormalizeReplicaRecordResultDTO, IpError]:
        """Execute universal normalization with version guard, diffing, and outbox emission."""
        bound_logger: FilteringBoundLogger = logger.bind(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream,
            replica_record_id=command.replica_record_id,
            replica_version=command.replica_version,
            trace_id=command.trace_id,
        )
        bound_logger.info("l3_normalization_started")

        # 1. Resolve Shard Info
        shard_info_result = await self._data_plane_uow_provider.resolve_shard_info(
            command.tenant_id
        )
        if shard_info_result.is_err:
            bound_logger.error(
                "tenant_shard_resolution_failed",
                error=shard_info_result.unwrap_err().message,
            )
            return Result.err(shard_info_result.unwrap_err())

        shard_id, shard_dsn = shard_info_result.unwrap()

        # 2. Look up stream transformation in Control Plane
        transformation = await self._control_plane_uow.transformations.get_by_stream(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream,
        )
        if transformation is None or transformation.mode == TransformationMode.DISABLED:
            bound_logger.info(
                "l3_normalization_skipped_no_transformation",
                mode=transformation.mode.value if transformation else "NONE",
            )
            return Result.ok(
                NormalizeReplicaRecordResultDTO(
                    outcome=NormalizationOutcome.SKIPPED_NO_TRANSFORMATION
                )
            )

        # 3. Open Data Plane Unit of Work and execute normalization atomically
        async with self._data_plane_uow_provider.get_data_plane_uow(
            command.tenant_id, shard_id, shard_dsn
        ) as uow:
            result = await self.normalize_replica_in_uow(
                uow=uow,
                transformation=transformation,
                command=command,
                event_policy=STANDALONE_OUTBOX_EVENT_POLICY,
            )
            if result.is_ok:
                await uow.commit()
            return result

    async def normalize_replica_in_uow(
        self,
        *,
        uow: IpDataPlaneUnitOfWorkPort,
        transformation: Transformation | None,
        command: NormalizeReplicaRecordCommand,
        replica: ReplicaRecord | None = None,
        event_policy: NormalizationEventPolicyPort | None = None,
    ) -> Result[NormalizeReplicaRecordResultDTO, IpError]:
        """Executes Layer 3 normalization inside an caller-managed Data Plane UoW without committing."""
        effective_policy = (
            event_policy if event_policy is not None else STANDALONE_OUTBOX_EVENT_POLICY
        )
        bound_logger: FilteringBoundLogger = logger.bind(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream,
            replica_record_id=command.replica_record_id,
            replica_version=command.replica_version,
            trace_id=command.trace_id,
        )

        if transformation is None or transformation.mode == TransformationMode.DISABLED:
            bound_logger.info(
                "l3_normalization_skipped_no_transformation",
                mode=transformation.mode.value if transformation else "NONE",
            )
            return Result.ok(
                NormalizeReplicaRecordResultDTO(
                    outcome=NormalizationOutcome.SKIPPED_NO_TRANSFORMATION
                )
            )

        # 4. Version Guard check: Idempotency & out-of-order protection
        if transformation.mode == TransformationMode.ACTIVE and await self._is_version_stale(
            uow, command, transformation
        ):
            await uow.traces.save_trace_event(
                transformation.build_skipped_stale_trace(
                    replica_version=command.replica_version,
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                )
            )
            bound_logger.info("l3_normalization_skipped_stale")
            return Result.ok(
                NormalizeReplicaRecordResultDTO(outcome=NormalizationOutcome.SKIPPED_STALE)
            )

        # 5. Resolve replica record (use caller-supplied aggregate when fused, else query UoW)
        resolved_replica = (
            replica
            if replica is not None
            else await uow.replica_records.get_by_id(
                tenant_id=command.tenant_id,
                record_id=command.replica_record_id,
            )
        )
        if resolved_replica is None:
            bound_logger.error("replica_record_not_found")
            return Result.err(ReplicaRecordNotFoundError.for_id(command.replica_record_id))

        # 6. Construct immutable ReplicaSnapshot & TransformationContext
        snapshot = ReplicaSnapshot(
            id=resolved_replica.id,
            connection_id=resolved_replica.connection_id,
            stream=resolved_replica.stream,
            record_key=resolved_replica.record_key,
            version=resolved_replica.version,
            data=resolved_replica.data,
            is_deleted=(resolved_replica.deleted_at is not None),
        )
        context = TransformationContext(
            connection_id=command.connection_id,
            stream=command.stream,
            tenant_id=command.tenant_id,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )

        # 7. Shadow-Only Mode: Never mutate canonical tables or emit CanonicalRecordChangedEvent
        if transformation.mode == TransformationMode.SHADOW:
            return await self._execute_shadow_only_mode(
                uow=uow,
                snapshot=snapshot,
                context=context,
                command=command,
                transformation=transformation,
                bound_logger=bound_logger,
            )

        # 8. Resolve active transformer
        transformer = self._transformer_registry.get(
            transformation.transformation_id, transformation.transformation_version
        )
        if transformer is None:
            return await self._handle_unregistered_transformer(
                uow=uow,
                command=command,
                transformation=transformation,
                target_version=transformation.transformation_version,
                bound_logger=bound_logger,
                rejection_strategy=_ACTIVE_REJECTION_STRATEGY,
            )

        # 9. Handle Tombstone: Cascade soft-delete to canonical domain entities
        if snapshot.is_deleted:
            return await self._handle_tombstone(
                uow=uow,
                command=command,
                transformation=transformation,
                bound_logger=bound_logger,
                event_policy=effective_policy,
            )

        # 10. Execute Transformer with strategy error handling
        transformation_result, early_result = await self._execute_transformer(
            transformer=transformer,
            snapshot=snapshot,
            context=context,
            command=command,
            transformation=transformation,
            uow=uow,
            bound_logger=bound_logger,
            rejection_strategy=_ACTIVE_REJECTION_STRATEGY,
        )
        if early_result is not None or transformation_result is None:
            assert early_result is not None
            return early_result

        ledger_entry = NormalizationLedgerEntry.begin(
            tenant_id=command.tenant_id,
            replica_record_id=command.replica_record_id,
            replica_version=command.replica_version,
            transformation_id=transformation.transformation_id,
            transformation_version=transformation.transformation_version,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            parent_trace_id=command.parent_trace_id,
            original_trace_id=command.original_trace_id,
            replay_count=command.replay_count,
        )

        # 11. Record explicit transformer rejections
        rejections_count = await self._record_transformer_rejections(
            uow, command, transformation, transformation_result
        )

        # 12. Evaluate Quality Rules, Resolve References & Upsert Canonical Drafts
        current_produced_refs, qr_rej_count = await self._apply_drafts_and_references(
            uow=uow,
            ledger_entry=ledger_entry,
            command=command,
            transformation=transformation,
            drafts=transformation_result.drafts,
        )
        rejections_count += qr_rej_count

        # 13. Tombstone Unseen Previous Drafts (Diffing)
        await self._tombstone_unseen_drafts(
            uow=uow,
            ledger_entry=ledger_entry,
            command=command,
            transformation=transformation,
            current_produced_refs=current_produced_refs,
        )

        # 14. Late-Arriving Reference Resolution & Back-Patching
        resolved_count = await self._resolve_late_arriving_references(
            uow=uow,
            ledger_entry=ledger_entry,
            command=command,
            current_produced_refs=current_produced_refs,
        )

        # 15. Active + Shadow Candidate Diff Calculation
        shadow_diff_count = await self._compute_and_record_shadow_diff(
            uow=uow,
            command=command,
            transformation=transformation,
            snapshot=snapshot,
            context=context,
            active_drafts=transformation_result.drafts,
        )

        # 16. Complete L3 Normalization Ledger Aggregate & apply event policy
        outcome = ledger_entry.complete_normalization(rejections_count=rejections_count)
        canonical_events = effective_policy.prepare_ledger_for_persistence(ledger_entry)
        await uow.normalization_ledger.record_entry(ledger_entry)

        bound_logger.info(
            "l3_normalization_completed",
            outcome=outcome.value,
            produced_count=len(current_produced_refs),
            rejections_count=rejections_count,
            resolved_refs_count=resolved_count,
        )

        return Result.ok(
            NormalizeReplicaRecordResultDTO(
                outcome=outcome,
                canonical_refs_produced=ledger_entry.produced_canonical_refs,
                canonical_events=canonical_events,
                rejections_count=rejections_count,
                shadow_diff_count=shadow_diff_count,
                resolved_references_count=resolved_count,
                canonical_payloads={
                    (d.canonical_type, d.source_id): dict(d.fields)
                    for d in transformation_result.drafts
                },
            )
        )

    async def _execute_shadow_only_mode(
        self,
        *,
        uow: IpDataPlaneUnitOfWorkPort,
        snapshot: ReplicaSnapshot,
        context: TransformationContext,
        command: NormalizeReplicaRecordCommand,
        transformation: Transformation,
        bound_logger: FilteringBoundLogger,
    ) -> Result[NormalizeReplicaRecordResultDTO, IpError]:
        """Execute transformer in SHADOW mode without mutating canonical tables or outbox."""
        if snapshot.is_deleted:
            bound_logger.info("l3_shadow_normalization_tombstone_noop")
            return Result.ok(
                NormalizeReplicaRecordResultDTO(outcome=NormalizationOutcome.TOMBSTONED)
            )

        candidate_version = (
            transformation.shadow_transformation_version
            if transformation.shadow_transformation_version is not None
            else transformation.transformation_version
        )
        candidate_transformer = self._transformer_registry.get(
            transformation.transformation_id, candidate_version
        )
        if candidate_transformer is None:
            return await self._handle_unregistered_transformer(
                uow=uow,
                command=command,
                transformation=transformation,
                target_version=candidate_version,
                bound_logger=bound_logger,
                rejection_strategy=_SHADOW_REJECTION_STRATEGY,
            )

        candidate_result, early_result = await self._execute_transformer(
            transformer=candidate_transformer,
            snapshot=snapshot,
            context=context,
            command=command,
            transformation=transformation,
            uow=uow,
            bound_logger=bound_logger,
            rejection_strategy=_SHADOW_REJECTION_STRATEGY,
        )
        if early_result is not None or candidate_result is None:
            assert early_result is not None
            return early_result

        rejections_count = await self._record_transformer_rejections(
            uow, command, transformation, candidate_result
        )

        active_drafts: tuple[CanonicalDraft, ...] = ()
        if (
            transformation.shadow_transformation_version is not None
            and transformation.shadow_transformation_version
            != transformation.transformation_version
        ):
            baseline_transformer = self._transformer_registry.get(
                transformation.transformation_id, transformation.transformation_version
            )
            if baseline_transformer is not None:
                try:
                    baseline_result = baseline_transformer.transform(snapshot, context)
                    active_drafts = baseline_result.drafts
                except Exception as exc:  # noqa: BLE001 - Shadow isolation boundary: failure in shadow baseline transform must not fail active normalization
                    logger.error(
                        "normalization_shadow_baseline_transform_failed",
                        tenant_id=command.tenant_id,
                        transformation_id=transformation.transformation_id,
                        version=transformation.transformation_version,
                        error=str(exc),
                    )

        diff_data = self._compute_shadow_diff(
            active_drafts=active_drafts,
            shadow_drafts=candidate_result.drafts,
        )
        shadow_diff_count = 0
        if diff_data:
            diff_entry = NormalizationShadowDiffEntry.create(
                tenant_id=command.tenant_id,
                replica_record_id=command.replica_record_id,
                candidate_version=candidate_version,
                diff_data=diff_data,
                trace_id=command.trace_id,
            )
            await uow.normalization_rejections.record_shadow_diff(diff_entry)
            shadow_diff_count = 1

        outcome = (
            NormalizationOutcome.REJECTED
            if rejections_count > 0 and not candidate_result.drafts
            else NormalizationOutcome.NORMALIZED
        )
        await uow.traces.save_trace_event(
            transformation.build_shadow_evaluation_trace(
                replica_record_id=snapshot.id,
                candidate_version=candidate_version,
                drafts_count=len(candidate_result.drafts),
                shadow_diff_count=shadow_diff_count,
                outcome=outcome,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
        )

        bound_logger.info(
            "l3_shadow_normalization_completed",
            candidate_version=candidate_version,
            shadow_diff_count=shadow_diff_count,
            rejections_count=rejections_count,
        )
        return Result.ok(
            NormalizeReplicaRecordResultDTO(
                outcome=outcome,
                canonical_refs_produced=(),
                rejections_count=rejections_count,
                shadow_diff_count=shadow_diff_count,
                resolved_references_count=0,
            )
        )

    async def _is_version_stale(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        command: NormalizeReplicaRecordCommand,
        transformation: Transformation,
    ) -> bool:
        latest_version = await uow.normalization_ledger.get_latest_version(
            tenant_id=command.tenant_id,
            replica_record_id=command.replica_record_id,
            transformation_id=transformation.transformation_id,
            transformation_version=transformation.transformation_version,
        )
        return latest_version is not None and latest_version >= command.replica_version

    async def _handle_unregistered_transformer(
        self,
        *,
        uow: IpDataPlaneUnitOfWorkPort,
        command: NormalizeReplicaRecordCommand,
        transformation: Transformation,
        target_version: int,
        bound_logger: FilteringBoundLogger,
        rejection_strategy: _RejectionPersistenceStrategy,
    ) -> Result[NormalizeReplicaRecordResultDTO, IpError]:
        bound_logger.error(
            "transformer_version_not_registered",
            transformation_id=transformation.transformation_id,
            transformation_version=target_version,
        )
        detail = f"Transformer '{transformation.transformation_id}' version {target_version} not found in registry."
        rejection = NormalizationRejectionEntry.create(
            tenant_id=command.tenant_id,
            replica_record_id=command.replica_record_id,
            stream=command.stream,
            transformation_id=transformation.transformation_id,
            transformation_version=target_version,
            reason_code=NormalizationRejectionReason.TRANSFORMER_ERROR.value,
            detail=detail,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        await rejection_strategy.record_terminal_rejection(
            uow=uow,
            command=command,
            transformation=transformation,
            rejection=rejection,
            detail=detail,
            summary_message=detail,
        )
        return Result.ok(
            NormalizeReplicaRecordResultDTO(
                outcome=NormalizationOutcome.REJECTED,
                rejections_count=1,
                error_detail="Transformer not found in registry",
            )
        )

    async def _handle_tombstone(
        self,
        *,
        uow: IpDataPlaneUnitOfWorkPort,
        command: NormalizeReplicaRecordCommand,
        transformation: Transformation,
        bound_logger: FilteringBoundLogger,
        event_policy: NormalizationEventPolicyPort,
    ) -> Result[NormalizeReplicaRecordResultDTO, IpError]:
        previous_refs = await uow.normalization_ledger.get_latest_produced_refs(
            tenant_id=command.tenant_id,
            replica_record_id=command.replica_record_id,
            transformation_id=transformation.transformation_id,
        )
        ledger_entry = NormalizationLedgerEntry.begin(
            tenant_id=command.tenant_id,
            replica_record_id=command.replica_record_id,
            replica_version=command.replica_version,
            transformation_id=transformation.transformation_id,
            transformation_version=transformation.transformation_version,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            parent_trace_id=command.parent_trace_id,
            original_trace_id=command.original_trace_id,
            replay_count=command.replay_count,
        )
        for canonical_type, source_id in previous_refs:
            writer = self._writer_registry.get(canonical_type)
            if writer is not None:
                await writer.soft_delete(
                    uow,
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    source_id=source_id,
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    parent_trace_id=command.parent_trace_id,
                    original_trace_id=command.original_trace_id,
                    replay_count=command.replay_count,
                )
            ledger_entry.record_canonical_tombstone(
                connection_id=command.connection_id,
                canonical_type=canonical_type,
                source_id=source_id,
            )

        outcome = ledger_entry.complete_tombstone(tombstoned_count=len(previous_refs))
        canonical_events = event_policy.prepare_ledger_for_persistence(ledger_entry)
        await uow.normalization_ledger.record_entry(ledger_entry)
        bound_logger.info(
            "l3_normalization_tombstoned",
            previous_refs_count=len(previous_refs),
        )
        return Result.ok(
            NormalizeReplicaRecordResultDTO(
                outcome=outcome,
                canonical_events=canonical_events,
            )
        )

    async def _execute_transformer(
        self,
        *,
        transformer: TransformerPort,
        snapshot: ReplicaSnapshot,
        context: TransformationContext,
        command: NormalizeReplicaRecordCommand,
        transformation: Transformation,
        uow: IpDataPlaneUnitOfWorkPort,
        bound_logger: FilteringBoundLogger,
        rejection_strategy: _RejectionPersistenceStrategy,
    ) -> tuple[
        TransformationResult | None, Result[NormalizeReplicaRecordResultDTO, IpError] | None
    ]:
        try:
            return transformer.transform(snapshot, context), None
        except Exception as exc:
            if self._error_policy.is_terminal_failure(exc):
                bound_logger.error("transformer_execution_terminal_failure", exc_info=exc)
                detail = str(exc)
                summary = f"Transformer execution failed: {exc}"
                rejection = NormalizationRejectionEntry.create(
                    tenant_id=command.tenant_id,
                    replica_record_id=command.replica_record_id,
                    stream=command.stream,
                    transformation_id=transformer.transformation_id,
                    transformation_version=transformer.transformation_version,
                    reason_code=NormalizationRejectionReason.TRANSFORMER_ERROR.value,
                    detail=detail,
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                )
                await rejection_strategy.record_terminal_rejection(
                    uow=uow,
                    command=command,
                    transformation=transformation,
                    rejection=rejection,
                    detail=detail,
                    summary_message=summary,
                )
                return None, Result.ok(
                    NormalizeReplicaRecordResultDTO(
                        outcome=NormalizationOutcome.REJECTED,
                        rejections_count=1,
                        error_detail=detail,
                    )
                )
            bound_logger.error("transformer_execution_transient_failure", exc_info=exc)
            return None, Result.err(
                NormalizationFailedError(
                    message=str(exc),
                    disposition=FailureDisposition.RETRY,
                    details={
                        "transformation_id": transformer.transformation_id,
                        "transformation_version": transformer.transformation_version,
                    },
                )
            )

    async def _record_transformer_rejections(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        command: NormalizeReplicaRecordCommand,
        transformation: Transformation,
        transformation_result: TransformationResult,
    ) -> int:
        for rej in transformation_result.rejections:
            rejection_entry = NormalizationRejectionEntry.create(
                tenant_id=command.tenant_id,
                replica_record_id=command.replica_record_id,
                stream=command.stream,
                transformation_id=transformation.transformation_id,
                transformation_version=transformation.transformation_version,
                reason_code=str(rej.reason),
                field_path=rej.field_path,
                detail=rej.detail,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
            await uow.normalization_rejections.record_rejection(rejection_entry)
        return len(transformation_result.rejections)

    async def _apply_drafts_and_references(
        self,
        *,
        uow: IpDataPlaneUnitOfWorkPort,
        ledger_entry: NormalizationLedgerEntry,
        command: NormalizeReplicaRecordCommand,
        transformation: Transformation,
        drafts: tuple[CanonicalDraft, ...],
    ) -> tuple[list[tuple[str, str]], int]:
        produced_refs: list[tuple[str, str]] = []
        rejected_count = 0

        for draft in drafts:
            draft_rejected, fields_dict, rej_entry = self._evaluate_draft_quality_rules(
                command, transformation, draft
            )
            if draft_rejected:
                if rej_entry is not None:
                    await uow.normalization_rejections.record_rejection(rej_entry)
                rejected_count += 1
                continue

            for ref in draft.references:
                target_writer = self._writer_registry.get(ref.target_canonical_type)
                resolved_target_id: str | None = None
                if target_writer is not None:
                    resolved_target_id = await target_writer.resolve_id(
                        uow,
                        tenant_id=command.tenant_id,
                        connection_id=command.connection_id,
                        source_id=ref.target_source_id,
                    )

                if resolved_target_id is not None:
                    fields_dict[ref.field_name] = resolved_target_id
                else:
                    pending_ref = PendingReferenceEntry.create(
                        tenant_id=command.tenant_id,
                        source_connection_id=command.connection_id,
                        target_canonical_type=ref.target_canonical_type,
                        target_source_id=ref.target_source_id,
                        referencing_canonical_type=draft.canonical_type,
                        referencing_source_id=draft.source_id,
                        referencing_field=ref.field_name,
                        trace_id=command.trace_id,
                    )
                    await uow.pending_references.record_pending(pending_ref)
                    ledger_entry.record_pending_reference(
                        field_name=ref.field_name,
                        target_canonical_type=ref.target_canonical_type,
                        target_source_id=ref.target_source_id,
                    )

            writer = self._writer_registry.get(draft.canonical_type)
            if writer is not None:
                await writer.upsert(
                    uow,
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    source_id=draft.source_id,
                    fields=fields_dict,
                    extensions=draft.extensions,
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    parent_trace_id=command.parent_trace_id,
                    original_trace_id=command.original_trace_id,
                    replay_count=command.replay_count,
                    transformation_id=transformation.transformation_id,
                    transformation_version=transformation.transformation_version,
                    replica_id=command.replica_record_id,
                    replica_version=command.replica_version,
                )

            produced_refs.append((draft.canonical_type, draft.source_id))
            ledger_entry.record_canonical_upsert(
                connection_id=command.connection_id,
                canonical_type=draft.canonical_type,
                source_id=draft.source_id,
                changed_fields=tuple(fields_dict.keys()),
            )

        return produced_refs, rejected_count

    def _evaluate_draft_quality_rules(
        self,
        command: NormalizeReplicaRecordCommand,
        transformation: Transformation,
        draft: CanonicalDraft,
    ) -> tuple[bool, JsonDict, NormalizationRejectionEntry | None]:
        entity_def = self._entity_registry.get(draft.canonical_type)
        fields_dict = dict(draft.fields)
        if entity_def is None:
            return False, fields_dict, None

        for rule in entity_def.quality_rules:
            failure_msg = rule.evaluate(fields_dict)
            if failure_msg is not None:
                if rule.severity == RuleSeverity.REJECT:
                    rej_entry = NormalizationRejectionEntry.create(
                        tenant_id=command.tenant_id,
                        replica_record_id=command.replica_record_id,
                        stream=command.stream,
                        transformation_id=transformation.transformation_id,
                        transformation_version=transformation.transformation_version,
                        reason_code=NormalizationRejectionReason.QUALITY_RULE_REJECTED.value,
                        field_path=rule.code,
                        detail=failure_msg,
                        trace_id=command.trace_id,
                        correlation_id=command.correlation_id,
                    )
                    return True, fields_dict, rej_entry
                if rule.severity == RuleSeverity.FLAG:
                    fields_dict["quality_flag"] = True

        return False, fields_dict, None

    async def _tombstone_unseen_drafts(
        self,
        *,
        uow: IpDataPlaneUnitOfWorkPort,
        ledger_entry: NormalizationLedgerEntry,
        command: NormalizeReplicaRecordCommand,
        transformation: Transformation,
        current_produced_refs: list[tuple[str, str]],
    ) -> None:
        previous_refs = await uow.normalization_ledger.get_latest_produced_refs(
            tenant_id=command.tenant_id,
            replica_record_id=command.replica_record_id,
            transformation_id=transformation.transformation_id,
        )
        unseen_refs = set(previous_refs) - set(current_produced_refs)
        for canonical_type, source_id in unseen_refs:
            writer = self._writer_registry.get(canonical_type)
            if writer is not None:
                await writer.soft_delete(
                    uow,
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    source_id=source_id,
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    parent_trace_id=command.parent_trace_id,
                    original_trace_id=command.original_trace_id,
                    replay_count=command.replay_count,
                )
            ledger_entry.record_unseen_draft_tombstone(
                connection_id=command.connection_id,
                canonical_type=canonical_type,
                source_id=source_id,
            )

    async def _resolve_late_arriving_references(
        self,
        *,
        uow: IpDataPlaneUnitOfWorkPort,
        ledger_entry: NormalizationLedgerEntry,
        command: NormalizeReplicaRecordCommand,
        current_produced_refs: list[tuple[str, str]],
    ) -> int:
        resolved_count = 0
        for canonical_type, source_id in current_produced_refs:
            resolved_entries = await uow.pending_references.resolve_pending_for_target(
                tenant_id=command.tenant_id,
                source_connection_id=command.connection_id,
                target_canonical_type=canonical_type,
                target_source_id=source_id,
            )
            if not resolved_entries:
                continue

            target_writer = self._writer_registry.get(canonical_type)
            resolved_target_id: str | None = None
            if target_writer is not None:
                resolved_target_id = await target_writer.resolve_id(
                    uow,
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    source_id=source_id,
                )
            effective_target_id = (
                resolved_target_id if resolved_target_id is not None else source_id
            )

            for entry in resolved_entries:
                referencing_writer = self._writer_registry.get(entry.referencing_canonical_type)
                if referencing_writer is not None:
                    await referencing_writer.resolve_reference(
                        uow,
                        tenant_id=command.tenant_id,
                        connection_id=command.connection_id,
                        source_id=entry.referencing_source_id,
                        field_name=entry.referencing_field,
                        target_id=effective_target_id,
                        trace_id=command.trace_id,
                    )
                ledger_entry.record_resolved_reference(
                    field_name=entry.referencing_field,
                    referencing_canonical_type=entry.referencing_canonical_type,
                    referencing_source_id=entry.referencing_source_id,
                    target_id=effective_target_id,
                )
            resolved_count += len(resolved_entries)
        return resolved_count

    async def _compute_and_record_shadow_diff(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        command: NormalizeReplicaRecordCommand,
        transformation: Transformation,
        snapshot: ReplicaSnapshot,
        context: TransformationContext,
        active_drafts: tuple[CanonicalDraft, ...],
    ) -> int:
        if transformation.shadow_transformation_version is None:
            return 0

        candidate_version = transformation.shadow_transformation_version
        if candidate_version == transformation.transformation_version:
            return 0

        shadow_transformer = self._transformer_registry.get(
            transformation.transformation_id, candidate_version
        )
        if shadow_transformer is None:
            return 0

        shadow_result = shadow_transformer.transform(snapshot, context)
        diff_data = self._compute_shadow_diff(
            active_drafts=active_drafts, shadow_drafts=shadow_result.drafts
        )
        if diff_data:
            diff_entry = NormalizationShadowDiffEntry.create(
                tenant_id=command.tenant_id,
                replica_record_id=command.replica_record_id,
                candidate_version=candidate_version,
                diff_data=diff_data,
                trace_id=command.trace_id,
            )
            await uow.normalization_rejections.record_shadow_diff(diff_entry)
            return 1
        return 0

    @staticmethod
    def _compute_shadow_diff(
        active_drafts: tuple[CanonicalDraft, ...],
        shadow_drafts: tuple[CanonicalDraft, ...],
    ) -> JsonDict:
        entity_diffs: list[EntityShadowDiff] = []
        active_by_key = {(d.canonical_type, d.source_id): d.fields for d in active_drafts}
        shadow_by_key = {(d.canonical_type, d.source_id): d.fields for d in shadow_drafts}

        all_keys = set(active_by_key.keys()) | set(shadow_by_key.keys())
        for canonical_type, source_id in all_keys:
            act_fields = active_by_key.get((canonical_type, source_id), {})
            shd_fields = shadow_by_key.get((canonical_type, source_id), {})
            if act_fields != shd_fields:
                changed_fields = tuple(
                    FieldShadowDiff(
                        field_name=f_name,
                        active_value=act_fields.get(f_name),
                        shadow_value=shd_fields.get(f_name),
                    )
                    for f_name in set(act_fields.keys()) | set(shd_fields.keys())
                    if act_fields.get(f_name) != shd_fields.get(f_name)
                )
                entity_diffs.append(
                    EntityShadowDiff(
                        canonical_type=canonical_type,
                        source_id=source_id,
                        field_diffs=changed_fields,
                    )
                )
        return {ed.entity_key: ed.to_json_dict() for ed in entity_diffs}
