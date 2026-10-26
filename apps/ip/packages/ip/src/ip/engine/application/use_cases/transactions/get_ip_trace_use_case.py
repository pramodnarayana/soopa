"""Use case for fetching the end-to-end 5-layer waterfall snapshot of an IP transaction trace."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from strace.domain import (
    TraceEvent,
    TraceLineageContext,
    TraceStatus,
    extract_deepest_lineage_context,
)

from ip.engine.application.dtos.trace import IpTraceDTO
from ip.engine.domain.exceptions import IpError, Result, TraceNotFoundError
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.domain.models.normalized_record import NormalizedRecord
from ip.engine.domain.models.outbound_record import OutboundRecord
from ip.engine.domain.models.replica_record import ReplicaRecord, ReplicaRejection
from ip.engine.domain.normalization import NormalizationRejectionEntry
from ip.engine.ports.outbound.uow import (
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)


@dataclass(frozen=True, kw_only=True)
class UpstreamTraceStages:
    """Hydrated L1, L2, and L3 upstream records for a partial-stage replay trace."""

    inbound_record: InboundRecord | None
    replica_records: list[ReplicaRecord]
    normalized_records: list[NormalizedRecord]


@dataclass(frozen=True, kw_only=True)
class GetIpTraceQuery:
    """Query to fetch the full 5-layer trace waterfall for a single trace_id."""

    tenant_id: str
    trace_id: str
    hydrate_payloads: bool = True


class GetIpTraceUseCase:
    """Assembles the 5-layer waterfall trace projection from UoW stage repositories and platform trace ledger."""

    def __init__(self, uow_provider: IpDataPlaneUnitOfWorkProviderPort) -> None:
        self._uow_provider = uow_provider

    @staticmethod
    def derive_overall_status(
        *,
        outbound_records: Sequence[OutboundRecord],
        normalization_rejections: Sequence[NormalizationRejectionEntry],
        normalized_records: Sequence[NormalizedRecord],
        replica_rejections: Sequence[ReplicaRejection],
        replica_records: Sequence[ReplicaRecord],
        inbound_record: InboundRecord | None,
    ) -> TraceStatus:
        """Derives the overall trace lifecycle status from its 5-layer stage records."""
        if outbound_records:
            return TraceStatus(outbound_records[-1].status.value)
        if normalization_rejections or replica_rejections:
            return TraceStatus.REJECTED
        if normalized_records:
            return TraceStatus.NORMALIZED
        if replica_records:
            return TraceStatus.REPLICATED
        if inbound_record is not None:
            return TraceStatus.INGESTED
        return TraceStatus.UNKNOWN

    @staticmethod
    def extract_lineage_context(
        *,
        trace_id: str,
        outbound_records: Sequence[OutboundRecord],
        normalized_records: Sequence[NormalizedRecord],
        inbound_record: InboundRecord | None,
        replica_records: Sequence[ReplicaRecord],
        trace_events: Sequence[TraceEvent],
    ) -> TraceLineageContext:
        """Extracts parent_trace_id, original_trace_id, replay_count, and correlation_id from the deepest stage."""
        fallback_correlation_id: str | None = None
        if replica_records:
            fallback_correlation_id = replica_records[-1].correlation_id
        elif trace_events:
            fallback_correlation_id = trace_events[-1].correlation_id

        return extract_deepest_lineage_context(
            trace_id=trace_id,
            stages_deepest_first=(
                outbound_records,
                normalized_records,
                (inbound_record,) if inbound_record is not None else (),
            ),
            fallback_correlation_id=fallback_correlation_id,
        )

    @staticmethod
    async def _hydrate_upstream_stages(
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        parent_trace_id: str | None,
        inbound_record: InboundRecord | None,
        replica_records: list[ReplicaRecord],
        normalized_records: list[NormalizedRecord],
        hydrate_payloads: bool,
    ) -> UpstreamTraceStages:
        current_parent_id = parent_trace_id
        hops = 0
        while current_parent_id and hops < 10:
            hops += 1
            next_parent_id: str | None = None

            if not normalized_records:
                p_nrms = list(
                    await uow.normalized_records.get_by_trace_id(current_parent_id, tenant_id)
                )
                if p_nrms:
                    normalized_records = p_nrms
                    next_parent_id = p_nrms[0].parent_trace_id

            if not replica_records:
                p_reps = list(
                    await uow.replica_records.get_by_trace_id(current_parent_id, tenant_id)
                )
                if p_reps:
                    replica_records = p_reps

            if inbound_record is None:
                p_inbs = await uow.inbound_records.get_by_trace_id(
                    current_parent_id,
                    tenant_id,
                    hydrate_payloads=hydrate_payloads,
                )
                if p_inbs:
                    inbound_record = p_inbs[-1]
                    if next_parent_id is None:
                        next_parent_id = inbound_record.parent_trace_id

            if inbound_record is not None and replica_records and normalized_records:
                break
            current_parent_id = next_parent_id

        return UpstreamTraceStages(
            inbound_record=inbound_record,
            replica_records=replica_records,
            normalized_records=normalized_records,
        )

    @classmethod
    async def assemble_in_uow(
        cls,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        trace_id: str,
        hydrate_payloads: bool = False,
    ) -> IpTraceDTO | None:
        """Assembles the 5-layer IpTraceDTO inside an active Data Plane Unit of Work."""
        inb_list = await uow.inbound_records.get_by_trace_id(
            trace_id,
            tenant_id,
            hydrate_payloads=hydrate_payloads,
        )
        inbound_record = inb_list[-1] if inb_list else None
        replica_records = list(await uow.replica_records.get_by_trace_id(trace_id, tenant_id))
        replica_rejections = list(await uow.replica_rejections.get_by_trace_id(trace_id, tenant_id))
        normalized_records = list(await uow.normalized_records.get_by_trace_id(trace_id, tenant_id))
        normalization_rejections = list(
            await uow.normalization_rejections.get_by_trace_id(trace_id, tenant_id)
        )
        entity_mappings = list(await uow.entity_maps.get_by_trace_id(trace_id, tenant_id))
        outbound_records = list(
            await uow.outbound_records.get_by_trace_id(
                trace_id,
                tenant_id,
                hydrate_payloads=hydrate_payloads,
            )
        )
        trace_events = await uow.traces.list_trace_events(tenant_id, trace_id)

        if not any(
            (
                inbound_record is not None,
                replica_records,
                replica_rejections,
                normalized_records,
                normalization_rejections,
                entity_mappings,
                outbound_records,
                trace_events,
            )
        ):
            return None

        lineage_ctx = cls.extract_lineage_context(
            trace_id=trace_id,
            outbound_records=outbound_records,
            normalized_records=normalized_records,
            inbound_record=inbound_record,
            replica_records=replica_records,
            trace_events=trace_events,
        )

        upstream = await cls._hydrate_upstream_stages(
            uow,
            tenant_id=tenant_id,
            parent_trace_id=lineage_ctx.parent_trace_id,
            inbound_record=inbound_record,
            replica_records=replica_records,
            normalized_records=normalized_records,
            hydrate_payloads=hydrate_payloads,
        )

        overall_status = cls.derive_overall_status(
            outbound_records=outbound_records,
            normalization_rejections=normalization_rejections,
            normalized_records=upstream.normalized_records,
            replica_rejections=replica_rejections,
            replica_records=upstream.replica_records,
            inbound_record=upstream.inbound_record,
        )

        return IpTraceDTO(
            trace_id=trace_id,
            tenant_id=tenant_id,
            correlation_id=lineage_ctx.correlation_id,
            original_trace_id=lineage_ctx.original_trace_id,
            parent_trace_id=lineage_ctx.parent_trace_id,
            replay_count=lineage_ctx.replay_count,
            status=overall_status,
            inbound_record=upstream.inbound_record,
            replica_records=tuple(upstream.replica_records),
            replica_rejections=tuple(replica_rejections),
            normalized_records=tuple(upstream.normalized_records),
            normalization_rejections=tuple(normalization_rejections),
            entity_mappings=tuple(entity_mappings),
            outbound_records=tuple(outbound_records),
            trace_events=tuple(trace_events),
        )

    async def execute(self, query: GetIpTraceQuery) -> Result[IpTraceDTO, IpError]:
        shard_res = await self._uow_provider.resolve_shard_info(query.tenant_id)
        if shard_res.is_err:
            return Result.err(shard_res.unwrap_err())

        shard_id, shard_dsn = shard_res.unwrap()
        async with self._uow_provider.get_data_plane_uow(
            query.tenant_id, shard_id, shard_dsn
        ) as uow:
            trace = await self.assemble_in_uow(
                uow,
                tenant_id=query.tenant_id,
                trace_id=query.trace_id,
                hydrate_payloads=query.hydrate_payloads,
            )
            if trace is None:
                return Result.err(TraceNotFoundError.for_trace(query.trace_id))
            return Result.ok(trace)


__all__ = ["GetIpTraceQuery", "GetIpTraceUseCase", "UpstreamTraceStages"]
