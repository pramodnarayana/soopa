"""Repository ports for IP replay ledger records."""

from __future__ import annotations

from typing import Protocol

from replay.domain.enums import ReplayTargetType

from ip.engine.domain.replay.models import IpReplayLedgerRecord


class IpReplayLedgerRepositoryPort(Protocol):
    """Abstract outbound repository port for `ip.ip_replay_ledger`."""

    async def save(self, record: IpReplayLedgerRecord) -> None:
        """Saves or updates a replay ledger record in the app's local transaction."""
        ...

    async def get_by_id(self, replay_id: str, tenant_id: str) -> IpReplayLedgerRecord | None:
        """Finds a replay ledger record by ID scoped to tenant."""
        ...

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> IpReplayLedgerRecord | None:
        """Finds a replay ledger record by unique idempotency key scoped to tenant."""
        ...

    async def list_by_target(
        self,
        tenant_id: str,
        target_type: ReplayTargetType,
        target_id: str,
        limit: int = 50,
    ) -> tuple[IpReplayLedgerRecord, ...]:
        """Lists historical replay ledger records for a batch or entity."""
        ...


IpReplayAuditRepositoryPort = IpReplayLedgerRepositoryPort
