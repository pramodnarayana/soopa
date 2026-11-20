"""Interface-segregated port for querying an L2 ReplicaRecord by stream and record key."""

from __future__ import annotations

from typing import Protocol

from ip.engine.domain.replication.replica_record import ReplicaRecord


class ReplicaLookupPort(Protocol):
    """Interface-segregated port for querying an L2 ReplicaRecord by stream and record key."""

    async def get_by_key(
        self,
        tenant_id: str,
        connection_id: str,
        stream: str,
        record_key: str,
    ) -> ReplicaRecord | None: ...
