"""
CQRS Data Plane Read Query Provider (`query_provider`).

Counterpart to `TenantDataPlaneUnitOfWorkProvider`. Routes read-only queries to
Pod Read Replicas by default while honoring polymorphic `ReadConsistencyPolicyPort`
strategies (e.g., `CausalWatermarkPolicy` for Read-Your-Own-Writes) and per-Pod
Writer fallback bulkheads.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator, Callable
from typing import Generic, TypeVar

import structlog

from sharding.application.read_consistency_policies import (
    EventualReplicaPolicy,
    TokenBucketWriterFallbackBulkhead,
)
from sharding.domain.constants import ReadRouteDisposition
from sharding.domain.exceptions import TenantNotFoundError
from sharding.domain.topology import ShardResolutionOutcome
from sharding.ports.outbound.read_consistency_port import (
    ReadConsistencyPolicyPort,
    ReplicaWatermarkProbePort,
    WriterFallbackBulkheadPort,
)
from sharding.ports.outbound.session_router_port import TenantReadSessionRouterPort
from sharding.ports.outbound.shard_resolver_port import CellularShardResolverPort

logger = structlog.get_logger(__name__)

TQueryRepo = TypeVar("TQueryRepo")
TReadSession = TypeVar("TReadSession")


class TenantDataPlaneQueryProvider(Generic[TQueryRepo, TReadSession]):
    """Generic CQRS Read Repository provider for B2B and Cellular Consumer apps."""

    def __init__(
        self,
        resolver: CellularShardResolverPort,
        read_router: TenantReadSessionRouterPort[TReadSession],
        query_repo_factory: Callable[[TReadSession], TQueryRepo],
        watermark_probe: ReplicaWatermarkProbePort | None = None,
        fallback_bulkhead: WriterFallbackBulkheadPort | None = None,
        default_policy: ReadConsistencyPolicyPort | None = None,
    ) -> None:
        self._resolver = resolver
        self._read_router = read_router
        self._query_repo_factory = query_repo_factory
        self._watermark_probe: ReplicaWatermarkProbePort | None = watermark_probe
        self._fallback_bulkhead: WriterFallbackBulkheadPort = (
            fallback_bulkhead
            if fallback_bulkhead is not None
            else TokenBucketWriterFallbackBulkhead()
        )
        self._default_policy: ReadConsistencyPolicyPort = (
            default_policy if default_policy is not None else EventualReplicaPolicy()
        )
        self._default_policy.validate_probe_configuration(self._watermark_probe)

    @contextlib.asynccontextmanager
    async def _open_routed_repository(
        self,
        tenant_id: str,
        resolution: ShardResolutionOutcome,
        consistency_policy: ReadConsistencyPolicyPort | None,
    ) -> AsyncGenerator[TQueryRepo, None]:
        if resolution.endpoint is None:
            logger.error(
                "query_provider_pod_resolution_failed",
                tenant_id=tenant_id,
                reason=resolution.reason.value if resolution.reason is not None else None,
            )
            raise TenantNotFoundError(
                f"Unable to resolve read Pod for tenant '{tenant_id}': {resolution.reason}"
            )

        active_policy = (
            consistency_policy if consistency_policy is not None else self._default_policy
        )
        active_policy.validate_probe_configuration(self._watermark_probe)
        decision = active_policy.select_route(
            endpoint=resolution.endpoint,
            watermark_probe=self._watermark_probe,
            fallback_bulkhead=self._fallback_bulkhead,
        )
        if decision.disposition == ReadRouteDisposition.CAUSAL_WRITER_FALLBACK:
            logger.info(
                "query_provider_routed_to_writer_fallback",
                tenant_id=tenant_id,
                shard_id=resolution.endpoint.shard_id,
                pool_key=decision.pool_key,
            )

        async with contextlib.aclosing(
            self._read_router.get_tenant_read_session(
                tenant_id,
                decision.pool_key,
                decision.target_dsn,
            )
        ) as session_gen:
            async for session in session_gen:
                yield self._query_repo_factory(session)
                break

    @contextlib.asynccontextmanager
    async def get_query_repository(
        self,
        tenant_id: str,
        consistency_policy: ReadConsistencyPolicyPort | None = None,
    ) -> AsyncGenerator[TQueryRepo, None]:
        """Acquire a Read-Replica-routed Query Repository for `tenant_id`."""
        resolution = await self._resolver.resolve_tenant_endpoint(tenant_id)
        async with self._open_routed_repository(tenant_id, resolution, consistency_policy) as repo:
            yield repo

    @contextlib.asynccontextmanager
    async def get_subject_query_repository(
        self,
        tenant_id: str,
        subject_key: str,
        consistency_policy: ReadConsistencyPolicyPort | None = None,
    ) -> AsyncGenerator[TQueryRepo, None]:
        """Acquire a Read-Replica-routed Query Repository for a Cellular `subject_key`."""
        resolution = await self._resolver.resolve_subject_endpoint(tenant_id, subject_key)
        async with self._open_routed_repository(tenant_id, resolution, consistency_policy) as repo:
            yield repo


__all__ = ["TenantDataPlaneQueryProvider"]
