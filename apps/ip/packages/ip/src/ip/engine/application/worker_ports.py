"""Application-layer worker execution ports for IP Orchestrator and Delivery workers.

Defines the abstract `Protocol` interfaces connecting inbound worker route registries
and outbound sharded adapters to IP Application Use Cases without coupling adapters
to one another.
"""

from __future__ import annotations

from typing import Protocol

from orchestration.domain.exceptions import Result as WorkflowResult
from orchestration.domain.exceptions import WorkflowError

from ip.engine.application.use_cases.delivery.deliver_outbound_record_use_case import (
    DeliverOutboundRecordCommand,
    DeliverOutboundRecordResponse,
)
from ip.engine.application.use_cases.ingestion.fetch_record_use_case import (
    FetchRecordCommand,
    FetchRecordResultDTO,
)
from ip.engine.application.use_cases.ingestion.run_sync_use_case import (
    RunSyncCommand,
    RunSyncResultDTO,
)
from ip.engine.application.use_cases.normalization.backfill_stream_normalization_use_case import (
    BackfillStreamNormalizationCommand,
    BackfillStreamNormalizationResultDTO,
)
from ip.engine.application.use_cases.normalization.normalize_replica_record_use_case import (
    NormalizeReplicaRecordCommand,
    NormalizeReplicaRecordResultDTO,
)
from ip.engine.application.use_cases.stitch.dispatch_canonical_event_to_stitches_use_case import (
    DispatchCanonicalEventResultDTO,
    DispatchCanonicalEventToStitchesCommand,
)
from ip.engine.application.use_cases.stitch.execute_stitch_worker_tick_use_case import (
    ExecuteStitchWorkerTickCommand,
    StitchWorkerTickResultDTO,
)
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.ports.inbound.worker_ports import IpStreamDefinitionResolver


class IpNormalizeReplicaExecutorPort(Protocol):
    """Port for executing Layer-3 replica normalization."""

    async def execute(
        self, command: NormalizeReplicaRecordCommand
    ) -> Result[NormalizeReplicaRecordResultDTO, IpError]: ...


class IpBackfillStreamNormalizationExecutorPort(Protocol):
    """Port for executing Layer-3 chunked stream normalization backfill."""

    async def execute(
        self, command: BackfillStreamNormalizationCommand
    ) -> Result[BackfillStreamNormalizationResultDTO, IpError]: ...


class IpStitchCanonicalDispatcherPort(Protocol):
    """Port for routing Layer-3 canonical events to Layer-4 Stitch runs and waiting steps."""

    async def execute(
        self, command: DispatchCanonicalEventToStitchesCommand
    ) -> WorkflowResult[DispatchCanonicalEventResultDTO, WorkflowError]: ...


class IpStitchWorkerTickExecutorPort(Protocol):
    """Port for executing a Layer-4 Stitch worker tick."""

    async def execute(
        self, command: ExecuteStitchWorkerTickCommand
    ) -> WorkflowResult[StitchWorkerTickResultDTO, WorkflowError]: ...


class IpOutboundDeliveryExecutorPort(Protocol):
    """Port for executing Layer-5 outbound deliveries."""

    async def execute(
        self, command: DeliverOutboundRecordCommand
    ) -> Result[DeliverOutboundRecordResponse, IpError]: ...


class IpFetchRecordExecutorPort(Protocol):
    """Port for executing Layer-1 Fetch-on-Notify pulls."""

    async def execute(self, command: FetchRecordCommand) -> FetchRecordResultDTO: ...


class IpRunSyncExecutorPort(Protocol):
    """Port for executing Layer-1 checkpointed pull syncs."""

    async def execute(self, command: RunSyncCommand) -> RunSyncResultDTO: ...


__all__ = [
    "IpBackfillStreamNormalizationExecutorPort",
    "IpFetchRecordExecutorPort",
    "IpNormalizeReplicaExecutorPort",
    "IpOutboundDeliveryExecutorPort",
    "IpRunSyncExecutorPort",
    "IpStitchCanonicalDispatcherPort",
    "IpStitchWorkerTickExecutorPort",
    "IpStreamDefinitionResolver",
]
