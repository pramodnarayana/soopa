"""Universal Layer 3 Canonical Normalization Use Case.

Orchestrates transforming Layer 2 Replica snapshots into Layer 3 Canonical domain entities
with idempotency version guards, tombstone cascade soft-deletes, differential reconciliation,
quality rules evaluation, reference resolution/back-patching, and shadow mode comparison
without raising exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from seedwork.domain.types import JsonDict
from structlog.typing import FilteringBoundLogger

from ip.engine.domain.enums import (
    CanonicalAction,
    FailureDisposition,
    IpTraceEventType,
    MappingMode,
    NormalizationOutcome,
    NormalizationRejectionReason,
    PipelineLayer,
    RuleSeverity,
    TimelineStatus,
)
from ip.engine.domain.events import CanonicalRecordChangedEvent
from ip.engine.domain.exceptions import (
    IpError,
    NormalizationFailedError,
    ReplicaRecordNotFoundError,
    Result,
)
from ip.engine.domain.models.replica_record import ReplicaRecord
from ip.engine.domain.models.timeline_entry import IpTraceEvent, TraceErrorDetails
from ip.engine.domain.normalization import (
    CanonicalDraft,
    EntityShadowDiff,
    FieldShadowDiff,
    MappingBinding,
    MappingContext,
    MappingResult,
    NormalizationLedgerEntry,
    NormalizationRejectionEntry,
    NormalizationShadowDiffEntry,
    PendingReferenceEntry,
    ReplicaSnapshot,
)
from ip.engine.ports.outbound.canonical_writer_port import (
    CanonicalEntityRegistryPort,
    CanonicalWriterRegistryPort,
)
from ip.engine.ports.outbound.mapper_port import MapperPort, MapperRegistryPort
from ip.engine.ports.outbound.normalization_error_policy_port import (
    NormalizationErrorPolicyPort,
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
    rejections_count: int = 0
    shadow_diff_count: int = 0
    resolved_references_count: int = 0
    error_detail: str | None = None


class NormalizeReplicaRecordUseCase:
    """Universal Layer 3 normalization orchestrator."""

    def __init__(
        self,
        control_plane_uow: IpControlPlaneUnitOfWorkPort,
        data_plane_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        mapper_registry: MapperRegistryPort,
        writer_registry: CanonicalWriterRegistryPort,
        entity_registry: CanonicalEntityRegistryPort,
        error_policy: NormalizationErrorPolicyPort,
    ) -> None:
        self._control_plane_uow = control_plane_uow
        self._data_plane_uow_provider = data_plane_uow_provider
        self._mapper_registry = mapper_registry
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

        # 2. Look up stream mapping binding in Control Plane
        binding = await self._control_plane_uow.mapping_bindings.get_by_stream(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream,
        )
        if binding is None or binding.mode == MappingMode.DISABLED:
            bound_logger.info(
                "l3_normalization_skipped_no_binding",
                mode=binding.mode.value if binding else "NONE",
            )
            return Result.ok(
                NormalizeReplicaRecordResultDTO(outcome=NormalizationOutcome.SKIPPED_NO_BINDING)
            )

        # 3. Open Data Plane Unit of Work
        async with self._data_plane_uow_provider.get_data_plane_uow(
            command.tenant_id, shard_id, shard_dsn
        ) as uow:
            # 4. Version Guard check: Idempotency & out-of-order protection
            if binding.mode == MappingMode.ACTIVE and await self._is_version_stale(
                uow, command, binding
            ):
                stale_replica = await uow.replica_records.get_by_id(
                    tenant_id=command.tenant_id,
                    record_id=command.replica_record_id,
                )
                if stale_replica is not None:
                    self._append_trace_event(
                        replica=stale_replica,
                        command=command,
                        binding=binding,
                        event_type=IpTraceEventType.L3_SKIPPED_STALE,
                        status=TimelineStatus.SUCCESS,
                        summary_message=(
                            f"Skipped stale replica version {command.replica_version} "
                            f"for mapper '{binding.mapping_id}' v{binding.mapping_version}."
                        ),
                    )
                    await uow.replica_records.save(stale_replica)
                    await uow.commit()
                bound_logger.info("l3_normalization_skipped_stale")
                return Result.ok(
                    NormalizeReplicaRecordResultDTO(outcome=NormalizationOutcome.SKIPPED_STALE)
                )

            # 5. Retrieve replica record
            replica = await uow.replica_records.get_by_id(
                tenant_id=command.tenant_id,
                record_id=command.replica_record_id,
            )
            if replica is None:
                bound_logger.error("replica_record_not_found")
                return Result.err(ReplicaRecordNotFoundError.for_id(command.replica_record_id))

            # 6. Construct ReplicaSnapshot & MappingContext
            snapshot = ReplicaSnapshot(
                id=replica.id,
                connection_id=replica.connection_id,
                stream=replica.stream,
                record_key=replica.record_key,
                version=replica.version,
                data=replica.data,
                is_deleted=(replica.deleted_at is not None),
            )
            context = MappingContext(
                connection_id=command.connection_id,
                stream=command.stream,
                tenant_id=command.tenant_id,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )

            # 7. Shadow-Only Mode: Never mutate canonical tables or emit CanonicalRecordChangedEvent
            if binding.mode == MappingMode.SHADOW:
                return await self._execute_shadow_only_mode(
                    uow=uow,
                    replica=replica,
                    snapshot=snapshot,
                    context=context,
                    command=command,
                    binding=binding,
                    bound_logger=bound_logger,
                )

            # 8. Resolve active mapper
            mapper = self._mapper_registry.get(binding.mapping_id, binding.mapping_version)
            if mapper is None:
                return await self._handle_unregistered_mapper(
                    uow=uow,
                    replica=replica,
                    command=command,
                    binding=binding,
                    target_version=binding.mapping_version,
                    bound_logger=bound_logger,
                )

            # 9. Handle Tombstone: Cascade soft-delete to canonical domain entities
            if snapshot.is_deleted:
                return await self._handle_tombstone(uow, replica, command, binding, bound_logger)

            # 10. Execute Mapper with strategy error handling
            mapping_result, early_result = await self._execute_mapper(
                mapper=mapper,
                replica=replica,
                snapshot=snapshot,
                context=context,
                command=command,
                binding=binding,
                uow=uow,
                bound_logger=bound_logger,
                record_ledger=True,
            )
            if early_result is not None or mapping_result is None:
                assert early_result is not None
                return early_result

            # 11. Record explicit mapper rejections
            rejections_count = await self._record_mapper_rejections(
                uow, command, binding, mapping_result
            )

            # 12. Evaluate Quality Rules, Resolve References & Upsert Canonical Drafts
            current_produced_refs, qr_rej_count = await self._apply_drafts_and_references(
                uow=uow,
                replica=replica,
                command=command,
                binding=binding,
                drafts=mapping_result.drafts,
            )
            rejections_count += qr_rej_count

            # 13. Tombstone Unseen Previous Drafts (Diffing)
            await self._tombstone_unseen_drafts(
                uow, replica, command, binding, current_produced_refs
            )

            # 14. Late-Arriving Reference Resolution & Back-Patching
            resolved_count = await self._resolve_late_arriving_references(
                uow, replica, command, binding, current_produced_refs
            )

            # 15. Active + Shadow Candidate Diff Calculation
            shadow_diff_count = await self._compute_and_record_shadow_diff(
                uow=uow,
                command=command,
                binding=binding,
                snapshot=snapshot,
                context=context,
                active_drafts=mapping_result.drafts,
            )

            # 16. Record Normalization Ledger Entry, Trace Event, Save Replica Events & Commit
            outcome = (
                NormalizationOutcome.NORMALIZED
                if current_produced_refs
                else (
                    NormalizationOutcome.REJECTED
                    if rejections_count > 0
                    else NormalizationOutcome.NORMALIZED
                )
            )
            self._append_trace_event(
                replica=replica,
                command=command,
                binding=binding,
                event_type=(
                    IpTraceEventType.L3_NORMALIZED
                    if outcome == NormalizationOutcome.NORMALIZED
                    else IpTraceEventType.L3_REJECTED
                ),
                status=(
                    TimelineStatus.SUCCESS
                    if outcome == NormalizationOutcome.NORMALIZED
                    else TimelineStatus.FAILED
                ),
                summary_message=(
                    f"Normalized replica '{replica.id}' v{command.replica_version} via "
                    f"'{binding.mapping_id}' v{binding.mapping_version}: "
                    f"{len(current_produced_refs)} canonical record(s), {rejections_count} rejection(s)."
                ),
            )
            await self._record_ledger_entry(
                uow,
                command,
                binding,
                tuple(current_produced_refs),
                outcome,
            )
            await uow.replica_records.save(replica)
            await uow.commit()

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
                    canonical_refs_produced=tuple(current_produced_refs),
                    rejections_count=rejections_count,
                    shadow_diff_count=shadow_diff_count,
                    resolved_references_count=resolved_count,
                )
            )

    async def _execute_shadow_only_mode(
        self,
        *,
        uow: IpDataPlaneUnitOfWorkPort,
        replica: ReplicaRecord,
        snapshot: ReplicaSnapshot,
        context: MappingContext,
        command: NormalizeReplicaRecordCommand,
        binding: MappingBinding,
        bound_logger: FilteringBoundLogger,
    ) -> Result[NormalizeReplicaRecordResultDTO, IpError]:
        """Execute mapper in SHADOW mode without mutating canonical tables or outbox."""
        if snapshot.is_deleted:
            bound_logger.info("l3_shadow_normalization_tombstone_noop")
            return Result.ok(
                NormalizeReplicaRecordResultDTO(outcome=NormalizationOutcome.TOMBSTONED)
            )

        candidate_version = (
            binding.shadow_mapping_version
            if binding.shadow_mapping_version is not None
            else binding.mapping_version
        )
        candidate_mapper = self._mapper_registry.get(binding.mapping_id, candidate_version)
        if candidate_mapper is None:
            return await self._handle_unregistered_mapper(
                uow=uow,
                replica=replica,
                command=command,
                binding=binding,
                target_version=candidate_version,
                bound_logger=bound_logger,
                record_ledger=False,
            )

        candidate_result, early_result = await self._execute_mapper(
            mapper=candidate_mapper,
            replica=replica,
            snapshot=snapshot,
            context=context,
            command=command,
            binding=binding,
            uow=uow,
            bound_logger=bound_logger,
            record_ledger=False,
        )
        if early_result is not None or candidate_result is None:
            assert early_result is not None
            return early_result

        rejections_count = await self._record_mapper_rejections(
            uow, command, binding, candidate_result
        )

        # If shadow_mapping_version differs from mapping_version and an active baseline mapper is registered, compare against it; otherwise compare against empty baseline ()
        active_drafts: tuple[CanonicalDraft, ...] = ()
        if (
            binding.shadow_mapping_version is not None
            and binding.shadow_mapping_version != binding.mapping_version
        ):
            baseline_mapper = self._mapper_registry.get(binding.mapping_id, binding.mapping_version)
            if baseline_mapper is not None:
                baseline_result = baseline_mapper.map(snapshot, context)
                active_drafts = baseline_result.drafts

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
        self._append_trace_event(
            replica=replica,
            command=command,
            binding=binding,
            event_type=(
                IpTraceEventType.L3_NORMALIZED
                if outcome == NormalizationOutcome.NORMALIZED
                else IpTraceEventType.L3_REJECTED
            ),
            status=(
                TimelineStatus.SUCCESS
                if outcome == NormalizationOutcome.NORMALIZED
                else TimelineStatus.FAILED
            ),
            summary_message=(
                f"Shadow-evaluated replica '{replica.id}' via "
                f"'{binding.mapping_id}' v{candidate_version}: "
                f"{len(candidate_result.drafts)} draft(s), {shadow_diff_count} diff(s)."
            ),
        )
        await uow.replica_records.save(replica)
        await uow.commit()

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
        binding: MappingBinding,
    ) -> bool:
        latest_version = await uow.normalization_ledger.get_latest_version(
            tenant_id=command.tenant_id,
            replica_record_id=command.replica_record_id,
            mapping_id=binding.mapping_id,
            mapping_version=binding.mapping_version,
        )
        return latest_version is not None and latest_version >= command.replica_version

    async def _handle_unregistered_mapper(
        self,
        *,
        uow: IpDataPlaneUnitOfWorkPort,
        replica: ReplicaRecord,
        command: NormalizeReplicaRecordCommand,
        binding: MappingBinding,
        target_version: int,
        bound_logger: FilteringBoundLogger,
        record_ledger: bool = True,
    ) -> Result[NormalizeReplicaRecordResultDTO, IpError]:
        bound_logger.error(
            "mapper_version_not_registered",
            mapping_id=binding.mapping_id,
            mapping_version=target_version,
        )
        detail = f"Mapper '{binding.mapping_id}' version {target_version} not found in registry."
        rejection = NormalizationRejectionEntry.create(
            tenant_id=command.tenant_id,
            replica_record_id=command.replica_record_id,
            stream=command.stream,
            mapping_id=binding.mapping_id,
            mapping_version=target_version,
            reason_code=NormalizationRejectionReason.MAPPER_ERROR.value,
            detail=detail,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        await uow.normalization_rejections.record_rejection(rejection)
        if record_ledger:
            await self._record_ledger_entry(
                uow, command, binding, (), NormalizationOutcome.REJECTED
            )
        self._append_trace_event(
            replica=replica,
            command=command,
            binding=binding,
            event_type=IpTraceEventType.L3_REJECTED,
            status=TimelineStatus.FAILED,
            summary_message=detail,
            error_details=TraceErrorDetails(
                reason=NormalizationRejectionReason.MAPPER_ERROR.value,
                detail=detail,
            ),
        )
        await uow.replica_records.save(replica)
        await uow.commit()
        return Result.ok(
            NormalizeReplicaRecordResultDTO(
                outcome=NormalizationOutcome.REJECTED,
                rejections_count=1,
                error_detail="Mapper not found in registry",
            )
        )

    async def _handle_tombstone(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        replica: ReplicaRecord,
        command: NormalizeReplicaRecordCommand,
        binding: MappingBinding,
        bound_logger: FilteringBoundLogger,
    ) -> Result[NormalizeReplicaRecordResultDTO, IpError]:
        previous_refs = await uow.normalization_ledger.get_latest_produced_refs(
            tenant_id=command.tenant_id,
            replica_record_id=command.replica_record_id,
            mapping_id=binding.mapping_id,
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
                )
            replica.add_domain_event(
                CanonicalRecordChangedEvent(
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    canonical_type=canonical_type,
                    source_id=source_id,
                    action=CanonicalAction.TOMBSTONE.value,
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    mapping_id=binding.mapping_id,
                    mapping_version=binding.mapping_version,
                    replica_id=command.replica_record_id,
                    replica_version=command.replica_version,
                    parent_trace_id=command.parent_trace_id,
                    original_trace_id=command.original_trace_id,
                    replay_count=command.replay_count,
                )
            )

        self._append_trace_event(
            replica=replica,
            command=command,
            binding=binding,
            event_type=IpTraceEventType.L3_TOMBSTONED,
            status=TimelineStatus.SUCCESS,
            summary_message=(
                f"Tombstoned {len(previous_refs)} canonical record(s) from replica '{replica.id}'."
            ),
        )
        await self._record_ledger_entry(uow, command, binding, (), NormalizationOutcome.TOMBSTONED)
        await uow.replica_records.save(replica)
        await uow.commit()
        bound_logger.info(
            "l3_normalization_tombstoned",
            previous_refs_count=len(previous_refs),
        )
        return Result.ok(NormalizeReplicaRecordResultDTO(outcome=NormalizationOutcome.TOMBSTONED))

    async def _execute_mapper(
        self,
        *,
        mapper: MapperPort,
        replica: ReplicaRecord,
        snapshot: ReplicaSnapshot,
        context: MappingContext,
        command: NormalizeReplicaRecordCommand,
        binding: MappingBinding,
        uow: IpDataPlaneUnitOfWorkPort,
        bound_logger: FilteringBoundLogger,
        record_ledger: bool,
    ) -> tuple[MappingResult | None, Result[NormalizeReplicaRecordResultDTO, IpError] | None]:
        try:
            return mapper.map(snapshot, context), None
        except Exception as exc:
            if self._error_policy.is_terminal_failure(exc):
                bound_logger.error("mapper_execution_terminal_failure", exc_info=exc)
                rejection = NormalizationRejectionEntry.create(
                    tenant_id=command.tenant_id,
                    replica_record_id=command.replica_record_id,
                    stream=command.stream,
                    mapping_id=mapper.mapping_id,
                    mapping_version=mapper.mapping_version,
                    reason_code=NormalizationRejectionReason.MAPPER_ERROR.value,
                    detail=str(exc),
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                )
                await uow.normalization_rejections.record_rejection(rejection)
                if record_ledger:
                    await self._record_ledger_entry(
                        uow, command, binding, (), NormalizationOutcome.REJECTED
                    )
                self._append_trace_event(
                    replica=replica,
                    command=command,
                    binding=binding,
                    event_type=IpTraceEventType.L3_REJECTED,
                    status=TimelineStatus.FAILED,
                    summary_message=f"Mapper execution failed: {exc}",
                    error_details=TraceErrorDetails(
                        reason=NormalizationRejectionReason.MAPPER_ERROR.value,
                        detail=str(exc),
                    ),
                )
                await uow.replica_records.save(replica)
                await uow.commit()
                return None, Result.ok(
                    NormalizeReplicaRecordResultDTO(
                        outcome=NormalizationOutcome.REJECTED,
                        rejections_count=1,
                        error_detail=str(exc),
                    )
                )
            bound_logger.error("mapper_execution_transient_failure", exc_info=exc)
            return None, Result.err(
                NormalizationFailedError(
                    message=str(exc),
                    disposition=FailureDisposition.RETRY,
                    details={
                        "mapping_id": mapper.mapping_id,
                        "mapping_version": mapper.mapping_version,
                    },
                )
            )

    async def _record_mapper_rejections(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        command: NormalizeReplicaRecordCommand,
        binding: MappingBinding,
        mapping_result: MappingResult,
    ) -> int:
        for rej in mapping_result.rejections:
            rejection_entry = NormalizationRejectionEntry.create(
                tenant_id=command.tenant_id,
                replica_record_id=command.replica_record_id,
                stream=command.stream,
                mapping_id=binding.mapping_id,
                mapping_version=binding.mapping_version,
                reason_code=str(rej.reason),
                field_path=rej.field_path,
                detail=rej.detail,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
            await uow.normalization_rejections.record_rejection(rejection_entry)
        return len(mapping_result.rejections)

    async def _apply_drafts_and_references(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        replica: ReplicaRecord,
        command: NormalizeReplicaRecordCommand,
        binding: MappingBinding,
        drafts: tuple[CanonicalDraft, ...],
    ) -> tuple[list[tuple[str, str]], int]:
        produced_refs: list[tuple[str, str]] = []
        rejected_count = 0

        for draft in drafts:
            draft_rejected, fields_dict, rej_entry = self._evaluate_draft_quality_rules(
                command, binding, draft
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
                    self._append_trace_event(
                        replica=replica,
                        command=command,
                        binding=binding,
                        event_type=IpTraceEventType.L3_REFERENCE_PENDING,
                        status=TimelineStatus.SUCCESS,
                        summary_message=(
                            f"Recorded pending reference '{ref.field_name}' -> "
                            f"({ref.target_canonical_type}, {ref.target_source_id})."
                        ),
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
                    mapping_id=binding.mapping_id,
                    mapping_version=binding.mapping_version,
                    replica_id=command.replica_record_id,
                    replica_version=command.replica_version,
                )

            produced_refs.append((draft.canonical_type, draft.source_id))
            replica.add_domain_event(
                CanonicalRecordChangedEvent(
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    canonical_type=draft.canonical_type,
                    source_id=draft.source_id,
                    action=CanonicalAction.UPSERT.value,
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    mapping_id=binding.mapping_id,
                    mapping_version=binding.mapping_version,
                    replica_id=command.replica_record_id,
                    replica_version=command.replica_version,
                    changed_fields=tuple(fields_dict.keys()),
                    parent_trace_id=command.parent_trace_id,
                    original_trace_id=command.original_trace_id,
                    replay_count=command.replay_count,
                )
            )

        return produced_refs, rejected_count

    def _evaluate_draft_quality_rules(
        self,
        command: NormalizeReplicaRecordCommand,
        binding: MappingBinding,
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
                        mapping_id=binding.mapping_id,
                        mapping_version=binding.mapping_version,
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
        uow: IpDataPlaneUnitOfWorkPort,
        replica: ReplicaRecord,
        command: NormalizeReplicaRecordCommand,
        binding: MappingBinding,
        current_produced_refs: list[tuple[str, str]],
    ) -> None:
        previous_refs = await uow.normalization_ledger.get_latest_produced_refs(
            tenant_id=command.tenant_id,
            replica_record_id=command.replica_record_id,
            mapping_id=binding.mapping_id,
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
                )
            replica.add_domain_event(
                CanonicalRecordChangedEvent(
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    canonical_type=canonical_type,
                    source_id=source_id,
                    action=CanonicalAction.TOMBSTONE.value,
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    mapping_id=binding.mapping_id,
                    mapping_version=binding.mapping_version,
                    replica_id=command.replica_record_id,
                    replica_version=command.replica_version,
                    parent_trace_id=command.parent_trace_id,
                    original_trace_id=command.original_trace_id,
                    replay_count=command.replay_count,
                )
            )
            self._append_trace_event(
                replica=replica,
                command=command,
                binding=binding,
                event_type=IpTraceEventType.L3_TOMBSTONED,
                status=TimelineStatus.SUCCESS,
                summary_message=(
                    f"Tombstoned unseen canonical draft ({canonical_type}, {source_id})."
                ),
            )

    async def _resolve_late_arriving_references(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        replica: ReplicaRecord,
        command: NormalizeReplicaRecordCommand,
        binding: MappingBinding,
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
                self._append_trace_event(
                    replica=replica,
                    command=command,
                    binding=binding,
                    event_type=IpTraceEventType.L3_REFERENCE_RESOLVED,
                    status=TimelineStatus.SUCCESS,
                    summary_message=(
                        f"Resolved pending reference '{entry.referencing_field}' on "
                        f"({entry.referencing_canonical_type}, {entry.referencing_source_id}) -> "
                        f"{effective_target_id}."
                    ),
                )
            resolved_count += len(resolved_entries)
        return resolved_count

    async def _compute_and_record_shadow_diff(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        command: NormalizeReplicaRecordCommand,
        binding: MappingBinding,
        snapshot: ReplicaSnapshot,
        context: MappingContext,
        active_drafts: tuple[CanonicalDraft, ...],
    ) -> int:
        if binding.shadow_mapping_version is None:
            return 0

        candidate_version = binding.shadow_mapping_version
        if candidate_version == binding.mapping_version:
            return 0

        shadow_mapper = self._mapper_registry.get(binding.mapping_id, candidate_version)
        if shadow_mapper is None:
            return 0

        shadow_result = shadow_mapper.map(snapshot, context)
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

    async def _record_ledger_entry(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        command: NormalizeReplicaRecordCommand,
        binding: MappingBinding,
        produced_refs: tuple[tuple[str, str], ...],
        outcome: NormalizationOutcome,
    ) -> None:
        ledger_entry = NormalizationLedgerEntry.create(
            tenant_id=command.tenant_id,
            replica_record_id=command.replica_record_id,
            replica_version=command.replica_version,
            mapping_id=binding.mapping_id,
            mapping_version=binding.mapping_version,
            produced_canonical_refs=produced_refs,
            outcome=outcome,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        await uow.normalization_ledger.record_entry(ledger_entry)

    @staticmethod
    def _append_trace_event(
        *,
        replica: ReplicaRecord,
        command: NormalizeReplicaRecordCommand,
        binding: MappingBinding,
        event_type: IpTraceEventType,
        status: TimelineStatus,
        summary_message: str,
        error_details: TraceErrorDetails | None = None,
    ) -> None:
        replica.add_trace_event(
            IpTraceEvent.create(
                tenant_id=command.tenant_id,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
                event_type=event_type.value,
                layer=PipelineLayer.L3_NORMALIZE,
                status=status,
                summary_message=summary_message,
                error_details=error_details,
                extra_metadata={
                    "mapping_id": binding.mapping_id,
                    "mapping_version": binding.mapping_version,
                },
            )
        )

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
