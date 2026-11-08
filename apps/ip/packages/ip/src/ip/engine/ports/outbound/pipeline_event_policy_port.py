"""Polymorphic event emission policies for Layer 2 and Layer 3 pipeline execution."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ip.engine.domain.normalization.events import CanonicalRecordChangedEvent
from ip.engine.domain.normalization.ledger import NormalizationLedgerEntry
from ip.engine.domain.replication.replica_record import ReplicaRecord


class ReplicationEventPolicyPort(Protocol):
    """Strategy governing whether Layer 2 replica mutations emit outbox events or hand off in memory."""

    def select_outbox_replicas(
        self, changed_replicas: Sequence[ReplicaRecord]
    ) -> tuple[ReplicaRecord, ...]:
        """Selects which mutated ReplicaRecord aggregates should drain domain events to outbox."""
        ...


class NormalizationEventPolicyPort(Protocol):
    """Strategy governing whether Layer 3 canonical mutations emit outbox events or hand off in memory."""

    def prepare_ledger_for_persistence(
        self, ledger_entry: NormalizationLedgerEntry
    ) -> tuple[CanonicalRecordChangedEvent, ...]:
        """Extracts produced canonical events and applies the outbox persistence policy to ledger_entry."""
        ...


__all__ = [
    "NormalizationEventPolicyPort",
    "ReplicationEventPolicyPort",
]
