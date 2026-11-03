"""Composition root factory assembling SqlAlchemyWorkflowUnitOfWork with concrete repositories."""

from __future__ import annotations

from collections.abc import Callable

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
from orchestration.adapters.outbound.database.uow import SqlAlchemyWorkflowUnitOfWork


def create_workflow_uow(
    session: AsyncSession,
    outbox_sink: Callable[[str, str, str | None, JsonDict], None] | None = None,
) -> SqlAlchemyWorkflowUnitOfWork:
    """Assemble SqlAlchemyWorkflowUnitOfWork with all 7 concrete SQLAlchemy repositories."""
    return SqlAlchemyWorkflowUnitOfWork(
        session,
        runs=SqlAlchemyWorkflowRunRepository(session, outbox_sink=outbox_sink),
        matches=SqlAlchemyWorkflowMatchRepository(session),
        queue=SqlAlchemyWorkflowQueueRepository(session),
        concurrency=SqlAlchemyWorkflowConcurrencyRepository(session),
        rate_limits=SqlAlchemyWorkflowRateLimitRepository(session),
        payloads=SqlAlchemyWorkflowPayloadStoreRepository(session),
        idempotency=SqlAlchemyWorkflowIdempotencyRepository(session),
    )


__all__ = ["create_workflow_uow"]
