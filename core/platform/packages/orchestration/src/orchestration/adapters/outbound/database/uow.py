"""SQLAlchemy Unit of Work implementation for the Durable Workflow Engine."""

from __future__ import annotations

from database.uow import BaseSqlAlchemyUnitOfWork
from sqlalchemy.ext.asyncio import AsyncSession

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
    """Concrete SQLAlchemy Unit of Work assembling all 7 Workflow Engine repository ports."""

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
        *,
        runs: WorkflowRunRepositoryPort,
        matches: WorkflowMatchRepositoryPort,
        queue: WorkflowQueuePort,
        concurrency: WorkflowConcurrencyPort,
        rate_limits: WorkflowRateLimitPort,
        payloads: WorkflowPayloadStorePort,
        idempotency: WorkflowIdempotencyPort,
    ) -> None:
        super().__init__(session)
        self.runs = runs
        self.matches = matches
        self.queue = queue
        self.concurrency = concurrency
        self.rate_limits = rate_limits
        self.payloads = payloads
        self.idempotency = idempotency


__all__ = ["SqlAlchemyWorkflowUnitOfWork"]
