"""SQLAlchemy Unit of Work implementation for the Durable Workflow Engine."""

from __future__ import annotations

from collections.abc import Callable

from database.uow import BaseSqlAlchemyUnitOfWork
from seedwork.domain.types import JsonDict
from sqlalchemy.ext.asyncio import AsyncSession

from orchestration.adapters.outbound.database.repositories import (
    SqlAlchemyWorkflowConcurrencyRepository,
    SqlAlchemyWorkflowIdempotencyRepository,
    SqlAlchemyWorkflowMatchRepository,
    SqlAlchemyWorkflowPayloadStoreRepository,
    SqlAlchemyWorkflowQueueRepository,
    SqlAlchemyWorkflowRateLimitRepository,
    SqlAlchemyWorkflowRunRepository,
)
from orchestration.ports.outbound.repository_ports import (
    WorkflowConcurrencyPort,
    WorkflowIdempotencyPort,
    WorkflowMatchRepositoryPort,
    WorkflowPayloadStorePort,
    WorkflowQueuePort,
    WorkflowRateLimitPort,
    WorkflowRunRepositoryPort,
    WorkflowUnitOfWorkPort,
)


class SqlAlchemyWorkflowUnitOfWork(BaseSqlAlchemyUnitOfWork, WorkflowUnitOfWorkPort):
    """Concrete SQLAlchemy Unit of Work assembling all 7 Workflow Engine repositories."""

    runs: WorkflowRunRepositoryPort
    matches: WorkflowMatchRepositoryPort
    queue: WorkflowQueuePort
    concurrency: WorkflowConcurrencyPort
    rate_limits: WorkflowRateLimitPort
    payloads: WorkflowPayloadStorePort
    idempotency: WorkflowIdempotencyPort

    def __init__(
        self,
        session: AsyncSession,
        outbox_sink: Callable[[str, str, str | None, JsonDict], None] | None = None,
    ) -> None:
        super().__init__(session)
        self.runs = SqlAlchemyWorkflowRunRepository(session, outbox_sink=outbox_sink)
        self.matches = SqlAlchemyWorkflowMatchRepository(session)
        self.queue = SqlAlchemyWorkflowQueueRepository(session)
        self.concurrency = SqlAlchemyWorkflowConcurrencyRepository(session)
        self.rate_limits = SqlAlchemyWorkflowRateLimitRepository(session)
        self.payloads = SqlAlchemyWorkflowPayloadStoreRepository(session)
        self.idempotency = SqlAlchemyWorkflowIdempotencyRepository(session)


__all__ = ["SqlAlchemyWorkflowUnitOfWork"]
