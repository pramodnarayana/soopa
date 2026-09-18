import contextlib
from typing import cast

from pubsub.message import SqsMessagePayload
from pubsub.ports.idempotency_repository_port import IdempotencyRepositoryPort
from sqlalchemy import CursorResult
from sqlalchemy.dialects.postgresql import insert

from database.router import DatabaseRouterPort
from edi.adapters.outbound.database.models.data_plane import ProcessedEvent
from edi.adapters.outbound.database.tenant_resolver import TenantResolver


class SqlAlchemyEdiIdempotencyRepository(IdempotencyRepositoryPort):
    """
    Concrete adapter for the EDI data plane to check and record idempotency.
    Uses the `processed_events` table in the EDI data plane.
    """

    def __init__(self, db_router: DatabaseRouterPort, resolver: TenantResolver) -> None:
        self.db_router = db_router
        self.resolver = resolver

    async def check_and_record_idempotency(self, payload: SqsMessagePayload) -> bool:
        """
        Attempts to extract tenant_id and idempotency_key from the payload.
        If missing, assumes the event is not idempotent and returns True.
        Otherwise, attempts to insert into the processed_events table.
        Returns True if successful (meaning the event is new).
        Returns False if a unique constraint violation occurs (meaning the event was already processed).
        """
        idempotency_key = payload.idempotency_key
        tenant_id = payload.tenant_id

        if not idempotency_key or not tenant_id:
            return True

        stmt = (
            insert(ProcessedEvent)
            .values(tenant_id=tenant_id, idempotency_key=idempotency_key)
            .on_conflict_do_nothing(index_elements=["tenant_id", "idempotency_key"])
        )

        shard_name, shard_dsn = await self.resolver.resolve_shard(tenant_id)
        async with contextlib.aclosing(
            self.db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)
        ) as session_gen:
            async for session in session_gen:
                result = await session.execute(stmt)
                await session.commit()
                return cast(CursorResult, result).rowcount > 0

        return False
