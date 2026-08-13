import json
import uuid
from typing import Any, Self

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.adapters.outbound.database.postgres_api_token_repository import PostgresApiTokenRepository
from ucp.adapters.outbound.database.postgres_app_repository import PostgresAppRepository
from ucp.adapters.outbound.database.tenant_repository import TenantRepository
from ucp.adapters.outbound.database.user_repository import UserRepository
from ucp.ports.uow import UcpUnitOfWorkPort


class SqlAlchemyUcpUnitOfWork(UcpUnitOfWorkPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tenant_repo = TenantRepository(session=self.session)
        self.user_repo = UserRepository(session=self.session)
        self.api_token_repo = PostgresApiTokenRepository(session=self.session)
        self.app_repo = PostgresAppRepository(session=self.session)
        self._events: list[dict[str, Any]] = []

    async def __aenter__(self) -> Self:
        await self.session.begin()
        return self

    async def __aexit__(self, exc_type: any, exc_val: any, exc_tb: any) -> None:
        if exc_type is not None:
            await self.rollback()
        # Note: We do NOT auto-commit on success here.
        # True UnitOfWork requires explicit .commit() call in the UseCase.

    async def commit(self) -> None:
        if self._events:
            query = text("""
                INSERT INTO ucp.outbox (id, event_type, payload, idempotency_key, tenant_id, status)
                VALUES (:id, :event_type, :payload, :idempotency_key, :tenant_id, 'PENDING')
            """)
            for event in self._events:
                await self.session.execute(
                    query,
                    {
                        "id": event["id"],
                        "event_type": event["event_type"],
                        "payload": json.dumps(event["payload"]),
                        "idempotency_key": event["idempotency_key"],
                        "tenant_id": event["tenant_id"],
                    },
                )
            self._events.clear()

        await self.session.commit()

    async def rollback(self) -> None:
        self._events.clear()
        await self.session.rollback()

    def register_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        self._events.append(
            {
                "id": str(uuid.uuid4()),
                "event_type": event_type,
                "payload": payload,
                "idempotency_key": idempotency_key,
                "tenant_id": tenant_id,
            }
        )
