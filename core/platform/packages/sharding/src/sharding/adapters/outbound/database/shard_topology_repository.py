"""
SQLAlchemy Outbound Adapter for Global Control Plane Shard & Cellular Bucket Topology.

Encapsulates all SQLAlchemy queries against `ucp.database_shards`, `ucp.shard_registry`,
`ucp.virtual_bucket_assignments`, `ucp.apps`, and `identity.tenants`, mapping rows via
strict dot-notation Data Mappers into pure `sharding.domain.topology` DTOs.
"""

from __future__ import annotations

import contextlib

from database.models.identity import Tenant
from database.models.sharding import (
    DatabaseShard,
    ShardRegistry,
    VirtualBucketAssignment,
)
from database.models.subscriptions import App
from database.router import DatabaseRouterPort
from sqlalchemy import select

from sharding.domain.constants import DatabaseShardStatus, ShardRoutingStrategy
from sharding.domain.topology import (
    ShardEndpointDTO,
    VirtualBucketAssignmentDTO,
)
from sharding.ports.outbound.shard_topology_repository_port import (
    ShardTopologyRepositoryPort,
)


def _to_shard_endpoint_dto(shard_obj: DatabaseShard) -> ShardEndpointDTO:
    """Explicit strict dot-notation Data Mapper from `DatabaseShard` ORM to `ShardEndpointDTO`."""
    writer_dsn = str(shard_obj.dsn)
    reader_dsn = str(shard_obj.reader_dsn) if shard_obj.reader_dsn else writer_dsn
    return ShardEndpointDTO(
        shard_id=str(shard_obj.id),
        shard_name=str(shard_obj.name),
        writer_dsn=writer_dsn,
        reader_dsn=reader_dsn,
        status=DatabaseShardStatus(str(shard_obj.status)),
        routing_strategy=ShardRoutingStrategy(str(shard_obj.routing_strategy)),
    )


def _to_bucket_assignment_dto(row: VirtualBucketAssignment) -> VirtualBucketAssignmentDTO:
    """Explicit strict dot-notation Data Mapper from `VirtualBucketAssignment` ORM to DTO."""
    return VirtualBucketAssignmentDTO(
        assignment_id=str(row.id),
        app_id=str(row.app_id),
        bucket_start=int(row.bucket_start),
        bucket_end=int(row.bucket_end),
        shard_id=str(row.shard_id),
    )


class SqlAlchemyShardTopologyRepository(ShardTopologyRepositoryPort):
    """Concrete SQLAlchemy implementation of `ShardTopologyRepositoryPort`."""

    def __init__(self, db_router: DatabaseRouterPort) -> None:
        self._db_router = db_router

    async def list_tenant_ids_for_app(self, app_slug: str) -> list[str]:
        """Fetch all active tenant IDs registered for `app_slug` from the Global Control Plane."""
        async with contextlib.aclosing(self._db_router.get_global_session()) as session_gen:
            async for session in session_gen:
                stmt = (
                    select(Tenant.id)
                    .join(ShardRegistry, Tenant.id == ShardRegistry.tenant_id)
                    .join(App, App.id == ShardRegistry.app_id)
                    .where(App.slug == app_slug)
                )
                result = await session.execute(stmt)
                return [str(t_id) for t_id in result.scalars().all()]
        return []

    async def get_tenant_shard_endpoint(
        self,
        tenant_id: str,
        app_slug: str,
    ) -> ShardEndpointDTO | None:
        """Fetch the mapped `ShardEndpointDTO` for `(tenant_id, app_slug)` or `None` if unmapped."""
        async with contextlib.aclosing(self._db_router.get_global_session()) as session_gen:
            async for session in session_gen:
                stmt = (
                    select(DatabaseShard)
                    .join(ShardRegistry, DatabaseShard.id == ShardRegistry.shard_id)
                    .join(Tenant, Tenant.id == ShardRegistry.tenant_id)
                    .join(App, App.id == ShardRegistry.app_id)
                    .where(Tenant.id == tenant_id, App.slug == app_slug)
                )
                result = await session.execute(stmt)
                shard_obj = result.scalars().first()
                if shard_obj is None:
                    return None
                return _to_shard_endpoint_dto(shard_obj)
        return None

    async def list_virtual_bucket_assignments_for_app(
        self,
        app_slug: str,
    ) -> list[tuple[VirtualBucketAssignmentDTO, ShardEndpointDTO]]:
        """Fetch ordered `(VirtualBucketAssignmentDTO, ShardEndpointDTO)` pairs for `app_slug`."""
        async with contextlib.aclosing(self._db_router.get_global_session()) as session_gen:
            async for session in session_gen:
                stmt = (
                    select(VirtualBucketAssignment, DatabaseShard)
                    .join(App, App.id == VirtualBucketAssignment.app_id)
                    .join(DatabaseShard, DatabaseShard.id == VirtualBucketAssignment.shard_id)
                    .where(App.slug == app_slug)
                    .order_by(VirtualBucketAssignment.bucket_start.asc())
                )
                result = await session.execute(stmt)
                rows = list(result.all())
                pairs: list[tuple[VirtualBucketAssignmentDTO, ShardEndpointDTO]] = []
                for assignment_obj, shard_obj in rows:
                    pairs.append(
                        (
                            _to_bucket_assignment_dto(assignment_obj),
                            _to_shard_endpoint_dto(shard_obj),
                        )
                    )
                return pairs
        return []


__all__ = ["SqlAlchemyShardTopologyRepository"]
