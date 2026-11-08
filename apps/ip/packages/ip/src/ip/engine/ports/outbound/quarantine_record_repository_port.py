"""Outbound port for persisting and querying Layer-5 QuarantineRecords."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ip.engine.domain.dispatch.quarantine_record import QuarantineRecord


class QuarantineRecordRepositoryPort(Protocol):
    """Repository port for the `public.quarantine_records` tenant-scoped DLQ ledger."""

    async def save(self, record: QuarantineRecord) -> None: ...

    async def get_by_id(self, record_id: str, tenant_id: str) -> QuarantineRecord | None: ...

    async def list_by_tenant(
        self,
        tenant_id: str,
        *,
        connection_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[QuarantineRecord]: ...


__all__ = ["QuarantineRecordRepositoryPort"]
