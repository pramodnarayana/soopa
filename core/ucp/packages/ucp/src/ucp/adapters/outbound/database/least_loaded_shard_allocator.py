from __future__ import annotations

import random
from collections.abc import Callable

import structlog
from seedwork.domain.exceptions import Result

from ucp.application.dto.shard_allocation import (
    ShardAllocationErrorCode,
    ShardAllocationProblem,
    ShardCandidateDTO,
)
from ucp.ports.outbound.shard_allocation_port import ShardAllocationStrategyPort
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


class LeastLoadedPooledShardStrategy(ShardAllocationStrategyPort):
    """
    Enterprise Gold Standard 1: Directory-based Shard Allocation Strategy.

    Features:
    1. Idempotency Guard: If the tenant already has an active shard for this app,
       preserves and returns the existing shard to prevent data orphaning.
    2. Power of Two Choices (P2C) Load Balancing: Mitigates thundering herd / herd clustering
       during concurrent tenant onboarding bursts.
    3. Transactional Cohesion: Operates entirely within the caller's UcpUnitOfWork session.
    4. First-Class Result Error Handling: Returns explicit Result instead of raising exceptions.
    """

    def __init__(
        self,
        sample_selector: Callable[[list[ShardCandidateDTO], int], list[ShardCandidateDTO]]
        | None = None,
    ) -> None:
        self._sample_selector = sample_selector or random.sample

    async def allocate_shard_for_app(
        self,
        uow: UcpUnitOfWorkPort,
        tenant_id: str,
        app_id: str,
        app_slug: str,
    ) -> Result[str, ShardAllocationProblem]:
        # 1. Idempotency Guard: Check if tenant is already allocated to a shard for this app
        existing_shard = await uow.tenant_repo.get_allocated_shard(tenant_id, app_id)
        if existing_shard:
            logger.info(
                "shard_allocation_idempotent_hit",
                tenant_id=tenant_id,
                app_id=app_id,
                app_slug=app_slug,
                shard_id=existing_shard,
            )
            return Result.ok(existing_shard)

        # 2. Query active candidate shards matching the app namespace
        candidates = await uow.tenant_repo.list_active_candidate_shards(app_slug, app_id)
        if not candidates:
            logger.error(
                "shard_pool_empty_or_exhausted",
                tenant_id=tenant_id,
                app_id=app_id,
                app_slug=app_slug,
            )
            return Result.err(
                ShardAllocationProblem(
                    code=ShardAllocationErrorCode.NO_ACTIVE_SHARDS,
                    message=f"No active database shard found for app '{app_slug}'",
                    app_slug=app_slug,
                    tenant_id=tenant_id,
                )
            )

        # 3. Placement Selection: P2C (Power of Two Choices)
        if len(candidates) == 1:
            chosen = candidates[0]
        else:
            sample = self._sample_selector(candidates, 2)
            c1, c2 = sample[0], sample[1]
            if c1.current_tenant_count < c2.current_tenant_count:
                chosen = c1
            elif c2.current_tenant_count < c1.current_tenant_count:
                chosen = c2
            else:
                # Deterministic tie-break by shard_id
                chosen = c1 if c1.shard_id <= c2.shard_id else c2

        logger.info(
            "shard_dynamically_allocated",
            tenant_id=tenant_id,
            app_id=app_id,
            app_slug=app_slug,
            shard_id=chosen.shard_id,
            current_tenant_count=chosen.current_tenant_count,
        )
        return Result.ok(chosen.shard_id)
