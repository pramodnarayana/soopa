from datetime import UTC, datetime, timedelta
from typing import Any

from database.models.idempotency import IdempotencyResult
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.domain.constants import IdempotencyStatus
from ucp.domain.exceptions import IdempotencyConflictError
from ucp.ports.outbound.idempotency_repository_port import IdempotencyRepositoryPort


class SqlAlchemyIdempotencyRepository(IdempotencyRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_result(
        self, tenant_id: str, idempotency_key: str
    ) -> tuple[bool, dict[str, Any] | None, int | None]:
        expires_at = datetime.now(UTC) + timedelta(hours=24)
        now = datetime.now(UTC)

        # Attempt to insert. If the row is new, we own the processing lock.
        # ON CONFLICT DO NOTHING ensures concurrent requests skip the insert cleanly.
        stmt = (
            insert(IdempotencyResult)
            .values(
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                status=IdempotencyStatus.IN_PROGRESS,
                expires_at=expires_at,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "idempotency_key"])
            .returning(IdempotencyResult.idempotency_key)
        )

        insert_result = await self.session.execute(stmt)
        inserted_key = insert_result.scalars().first()

        if inserted_key:
            # We just inserted it, so we own the processing lock
            return False, None, None

        # Row already exists, so let's fetch it
        result = await self.session.execute(
            select(IdempotencyResult).where(
                IdempotencyResult.tenant_id == tenant_id,
                IdempotencyResult.idempotency_key == idempotency_key,
            )
        )
        record = result.scalars().first()

        if not record:
            # Extremely rare race condition (deleted right after our insert failed)
            return False, None, None

        # Check expiration first - expired records should be regenerated
        if record.expires_at <= now:
            # Record has expired, allow re-processing by replacing it
            record.status = IdempotencyStatus.IN_PROGRESS
            record.expires_at = expires_at
            record.response_body = None
            record.response_status_code = None
            record.updated_at = now
            await self.session.flush()
            return False, None, None

        if record.status == IdempotencyStatus.COMPLETED:
            return True, record.response_body, record.response_status_code
        elif record.status == IdempotencyStatus.IN_PROGRESS:
            raise IdempotencyConflictError(
                f"Request with idempotency key {idempotency_key} is already in progress."
            )
        else:
            return False, None, None

    async def save_result(
        self,
        tenant_id: str,
        idempotency_key: str,
        response_body: dict[str, Any],
        response_status_code: int,
    ) -> None:
        result = await self.session.execute(
            select(IdempotencyResult)
            .where(
                IdempotencyResult.tenant_id == tenant_id,
                IdempotencyResult.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )
        record = result.scalars().first()
        if record:
            record.status = IdempotencyStatus.COMPLETED
            record.response_body = response_body
            record.response_status_code = response_status_code
            record.updated_at = datetime.now(UTC)
