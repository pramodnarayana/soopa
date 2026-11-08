"""Concrete polymorphic event emission strategies for standalone vs fused pipeline execution."""

from __future__ import annotations

from collections.abc import Sequence

from ip.engine.domain.normalization.events import CanonicalRecordChangedEvent
from ip.engine.domain.normalization.ledger import NormalizationLedgerEntry
from ip.engine.domain.replication.replica_record import ReplicaRecord


class StandaloneOutboxEventPolicy:
    """Preserves domain events on L2/L3 aggregates so repositories drain them to ip_outbox."""

    def select_outbox_replicas(
        self, changed_replicas: Sequence[ReplicaRecord]
    ) -> tuple[ReplicaRecord, ...]:
        """Returns all changed replicas for transactional outbox emission."""
        return tuple(changed_replicas)

    def prepare_ledger_for_persistence(
        self, ledger_entry: NormalizationLedgerEntry
    ) -> tuple[CanonicalRecordChangedEvent, ...]:
        """Captures CanonicalRecordChangedEvents while keeping them staged for ip_outbox."""
        return tuple(
            event
            for event in ledger_entry.domain_events
            if isinstance(event, CanonicalRecordChangedEvent)
        )


class FusedInMemoryEventPolicy:
    """Suppresses intermediate L2/L3 outbox queue hops during fused single-transaction execution."""

    def select_outbox_replicas(
        self, changed_replicas: Sequence[ReplicaRecord]
    ) -> tuple[ReplicaRecord, ...]:
        """Clears L2 domain events in memory while preserving trace events."""
        for replica in changed_replicas:
            replica.clear_domain_events()
        return ()

    def prepare_ledger_for_persistence(
        self, ledger_entry: NormalizationLedgerEntry
    ) -> tuple[CanonicalRecordChangedEvent, ...]:
        """Extracts CanonicalRecordChangedEvents for in-memory L4 handoff and clears ledger domain events."""
        captured = tuple(
            event
            for event in ledger_entry.domain_events
            if isinstance(event, CanonicalRecordChangedEvent)
        )
        ledger_entry.clear_domain_events()
        return captured


STANDALONE_OUTBOX_EVENT_POLICY = StandaloneOutboxEventPolicy()
FUSED_IN_MEMORY_EVENT_POLICY = FusedInMemoryEventPolicy()

__all__ = [
    "FUSED_IN_MEMORY_EVENT_POLICY",
    "STANDALONE_OUTBOX_EVENT_POLICY",
    "FusedInMemoryEventPolicy",
    "StandaloneOutboxEventPolicy",
]
