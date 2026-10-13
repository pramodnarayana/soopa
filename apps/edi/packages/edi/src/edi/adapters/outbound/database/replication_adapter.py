"""
SQLAlchemy Replication Adapter.

Implements the ReplicationPort by reading the REPLICATION_GRAPH declarative
registry and driving entity replication in the topologically correct order.

Design invariants:
    - This adapter contains zero hardcoded entity or dependency knowledge.
      All FK dependency semantics live in replication_registry.py.
    - The topological_layers algorithm (in edi.domain.replication) is the single
      authoritative source of insertion and deletion order.
    - Every public method delegates to one of two generic drivers:
        _replicate_with_dependencies  (granular: one entity at a time)
        _do_replicate                 (bulk: full tenant state sync)
"""

from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from typing import ClassVar, Protocol, cast

import structlog
from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import Select, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped

from database.router import DatabaseRouter
from edi.adapters.outbound.database.replication_registry import REPLICATION_GRAPH
from edi.domain.replication import (
    EntityDependency,
    EntitySpec,
    MapperFunc,
    PermanentProvisioningError,
    TransientProvisioningError,
    topological_layers,
)
from edi.ports.outbound.replication_port import ReplicationPort
from edi.ports.outbound.tenant_port import TenantPort

logger = structlog.get_logger(__name__)

SHARED_TENANT_ID = PLATFORM_TENANT_ID


class ReplicatedModel(Protocol):
    __tablename__: ClassVar[str]
    id: Mapped[str]
    tenant_id: Mapped[str | None]


# Compute once at module load — the graph is static for the lifetime of the process.
# Any cycle in the graph raises ValueError immediately at startup, not silently at runtime.
_TOPOLOGICAL_LAYERS: list[list[str]] = topological_layers(REPLICATION_GRAPH)
_REVERSE_TOPOLOGICAL_LAYERS: list[list[str]] = list(reversed(_TOPOLOGICAL_LAYERS))


class SqlAlchemyReplicationAdapter(ReplicationPort):
    def __init__(self, db_router: DatabaseRouter, tenant_port: TenantPort) -> None:
        self.db_router = db_router
        self.tenant_port = tenant_port

    # -----------------------------------------------------------------------
    # Full Sync Driver
    # -----------------------------------------------------------------------

    async def replicate_tenant_configuration(self, tenant_id: str) -> None:
        """
        Full topological state sync.
        Used for initial tenant provisioning or disaster recovery reconciliation.
        """
        async with self._get_sessions(tenant_id) as (global_session, tenant_session):
            try:
                # 1. Upsert all entities in top-down topological order
                for layer in _TOPOLOGICAL_LAYERS:
                    for entity_key in layer:
                        spec = REPLICATION_GRAPH[entity_key]
                        stmt = _build_fetch_all_stmt(spec, tenant_id)
                        res = await global_session.execute(stmt)
                        entities = res.scalars().all()

                        rows_to_upsert: list[dict[str, object]] = []
                        for entity in entities:
                            if hasattr(entity, "tenant_id"):
                                source_tenant_id = cast(str | None, entity.tenant_id)
                                if not source_tenant_id:
                                    raise PermanentProvisioningError(
                                        f"Data integrity violation: {entity.__class__.__name__} "
                                        f"id={entity.id} has a null tenant_id in the global DB."
                                    )
                            else:
                                source_tenant_id = tenant_id

                            data = dict(spec.mapper(entity))
                            if data.get("tenant_id") is None:
                                data["tenant_id"] = source_tenant_id
                            rows_to_upsert.append(data)

                        if rows_to_upsert:
                            await self._upsert_batch(
                                tenant_session,
                                rows_to_upsert,
                                spec.data_plane_model,
                            )
                        await tenant_session.flush()

                # 2. Sync deletes in bottom-up topological order
                for layer in _REVERSE_TOPOLOGICAL_LAYERS:
                    for entity_key in layer:
                        spec = REPLICATION_GRAPH[entity_key]
                        await self._sync_deletes(
                            tenant_id,
                            global_session,
                            tenant_session,
                            spec.control_plane_model,
                            spec.data_plane_model,
                            spec.include_shared,
                        )

                await tenant_session.commit()
                logger.info(
                    "replication_full_sync_completed",
                    tenant_id=tenant_id,
                )

            except PermanentProvisioningError:
                await tenant_session.rollback()
                raise
            except Exception as e:
                await tenant_session.rollback()
                logger.exception(
                    "replication_full_sync_failed",
                    tenant_id=tenant_id,
                    reason=str(e),
                )
                raise TransientProvisioningError(
                    f"Full replication failed for tenant {tenant_id}: {e}"
                ) from e

    # -----------------------------------------------------------------------
    # Session Context Managers
    # -----------------------------------------------------------------------

    @asynccontextmanager
    async def _get_sessions(
        self, tenant_id: str
    ) -> AsyncIterator[tuple[AsyncSession, AsyncSession]]:
        try:
            shard_name, shard_dsn = await self.tenant_port.resolve_shard(tenant_id)
        except (TimeoutError, ConnectionError) as e:
            raise TransientProvisioningError(
                f"Transient network failure resolving tenant {tenant_id}: {e}"
            ) from e
        except Exception as e:
            raise PermanentProvisioningError(f"Tenant {tenant_id} unresolvable: {e}") from e

        global_gen = self.db_router.get_global_session()
        tenant_gen = self.db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)

        async with aclosing(global_gen) as global_ctx, aclosing(tenant_gen) as tenant_ctx:
            global_session = await global_ctx.__anext__()
            tenant_session = await tenant_ctx.__anext__()
            yield global_session, tenant_session

    @asynccontextmanager
    async def _get_tenant_session(self, tenant_id: str) -> AsyncIterator[AsyncSession]:
        try:
            shard_name, shard_dsn = await self.tenant_port.resolve_shard(tenant_id)
        except (TimeoutError, ConnectionError) as e:
            raise TransientProvisioningError(
                f"Transient network failure resolving tenant {tenant_id}: {e}"
            ) from e
        except Exception as e:
            raise PermanentProvisioningError(f"Tenant {tenant_id} unresolvable: {e}") from e

        tenant_gen = self.db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)
        async with aclosing(tenant_gen) as tenant_ctx:
            tenant_session = await tenant_ctx.__anext__()
            yield tenant_session

    # -----------------------------------------------------------------------
    # Generic Granular Replication Driver (dependency-aware, one entity)
    # -----------------------------------------------------------------------

    async def _pre_replicate_dependency(
        self,
        global_session: AsyncSession,
        tenant_session: AsyncSession,
        entity: DeclarativeBase | ReplicatedModel,
        spec: EntitySpec,
        dep: EntityDependency,
        tenant_id: str,
        entity_id: str,
    ) -> None:
        if not hasattr(entity, dep.fk_attr):
            raise PermanentProvisioningError(
                f"Entity {spec.control_plane_model.__name__} is missing declared FK attribute '{dep.fk_attr}'"
            )
        dep_id: str | None = getattr(entity, dep.fk_attr)
        if not dep_id:
            return

        dep_spec = REPLICATION_GRAPH[dep.target_key]
        logger.info(
            "replication_dependency_pre_replication_started",
            entity_type=spec.control_plane_model.__name__,
            entity_id=entity_id,
            dependency_type=dep_spec.control_plane_model.__name__,
            dependency_id=dep_id,
            tenant_id=tenant_id,
        )

        dep_model = cast(type[ReplicatedModel], dep_spec.control_plane_model)
        dep_stmt = select(dep_model).where(dep_model.id == dep_id)
        if dep_spec.include_shared:
            dep_stmt = dep_stmt.where(
                (dep_model.tenant_id == tenant_id) | (dep_model.tenant_id == SHARED_TENANT_ID)
            )
        else:
            dep_stmt = dep_stmt.where(dep_model.tenant_id == tenant_id)
        dep_res = await global_session.execute(dep_stmt)
        dep_entity = dep_res.scalars().first()

        if not dep_entity:
            raise PermanentProvisioningError(
                f"FK dependency {dep_spec.control_plane_model.__name__} id={dep_id} "
                f"(required by {spec.control_plane_model.__name__} id={entity_id}) "
                "not found in global DB. The row may have been deleted. "
                "Sending to DLQ."
            )

        if hasattr(dep_entity, "tenant_id"):
            dep_tenant_id = cast(str | None, dep_entity.tenant_id)
            if not dep_tenant_id:
                raise PermanentProvisioningError(
                    f"Data integrity violation: {dep_entity.__class__.__name__} "
                    f"id={dep_entity.id} has a null tenant_id in the global DB."
                )
        else:
            dep_tenant_id = tenant_id

        await self._upsert_entity(
            tenant_session,
            dep_tenant_id,
            cast(DeclarativeBase, dep_entity),
            dep_spec.data_plane_model,
            dep_spec.mapper,
        )
        logger.info(
            "replication_dependency_pre_replication_completed",
            dependency_type=dep_spec.control_plane_model.__name__,
            dependency_id=dep_id,
            tenant_id=dep_tenant_id,
        )

    async def _replicate_with_dependencies(
        self, tenant_id: str, entity_id: str, entity_key: str
    ) -> None:
        """
        Granular replication driver. Reads the REPLICATION_GRAPH spec for the
        given entity key, pre-replicates all non-null FK dependencies to the
        tenant shard in order, and then upserts the target entity.
        """
        spec = REPLICATION_GRAPH[entity_key]

        async with self._get_sessions(tenant_id) as (global_session, tenant_session):
            try:
                # 1. Fetch the target entity from the global DB
                entity = await self._fetch_global_entity(global_session, spec, tenant_id, entity_id)

                # 2. Pre-replicate dependencies in declared order
                for dep in spec.dependencies:
                    await self._pre_replicate_dependency(
                        global_session,
                        tenant_session,
                        entity,
                        spec,
                        dep,
                        tenant_id,
                        entity_id,
                    )

                # 3. Upsert the entity — all FK dependencies are now guaranteed to exist
                if hasattr(entity, "tenant_id"):
                    source_tenant_id = cast(str | None, entity.tenant_id)
                    if not source_tenant_id:
                        raise PermanentProvisioningError(
                            f"Data integrity violation: {entity.__class__.__name__} "
                            f"id={getattr(entity, 'id', 'unknown')} has a null tenant_id in the global DB."
                        )
                else:
                    source_tenant_id = tenant_id

                await self._upsert_entity(
                    tenant_session, source_tenant_id, entity, spec.data_plane_model, spec.mapper
                )
                await tenant_session.commit()
                logger.info(
                    "replication_entity_completed",
                    entity_type=spec.control_plane_model.__name__,
                    entity_id=entity_id,
                    tenant_id=tenant_id,
                )

            except (TransientProvisioningError, PermanentProvisioningError):
                await tenant_session.rollback()
                raise
            except Exception as e:
                await tenant_session.rollback()
                logger.exception(
                    "replication_entity_failed",
                    entity_type=spec.control_plane_model.__name__,
                    entity_id=entity_id,
                    tenant_id=tenant_id,
                    reason=str(e),
                )
                raise TransientProvisioningError(
                    f"Failed to replicate {spec.control_plane_model.__name__} id={entity_id}: {e}"
                ) from e

    async def _fetch_global_entity(
        self,
        global_session: AsyncSession,
        spec: EntitySpec,
        tenant_id: str,
        entity_id: str,
    ) -> DeclarativeBase:
        """Fetches a single entity from the global DB with correct tenant scoping."""
        spec_model = cast(type[ReplicatedModel], spec.control_plane_model)
        stmt = select(spec_model).where(spec_model.id == entity_id)
        if spec.include_shared:
            stmt = stmt.where(
                (spec_model.tenant_id == tenant_id) | (spec_model.tenant_id == SHARED_TENANT_ID)
            )
        else:
            stmt = stmt.where(spec_model.tenant_id == tenant_id)

        res = await global_session.execute(stmt)
        entity = res.scalars().first()

        if not entity:
            raise PermanentProvisioningError(
                f"{spec.control_plane_model.__name__} id={entity_id} not found "
                f"in global DB for tenant={tenant_id}."
            )
        return cast(DeclarativeBase, entity)

    # -----------------------------------------------------------------------
    # Public Granular Replication Methods
    # Each is a single-line delegation to _replicate_with_dependencies.
    # -----------------------------------------------------------------------

    async def replicate_as2_partner(self, tenant_id: str, partner_id: str) -> None:
        await self._replicate_with_dependencies(tenant_id, partner_id, "as2_partner")

    async def delete_as2_partner(self, tenant_id: str, partner_id: str) -> None:
        spec = REPLICATION_GRAPH["as2_partner"]
        await self._granular_delete(
            tenant_id, partner_id, spec.data_plane_model, include_shared=spec.include_shared
        )

    async def replicate_as2_partnership(self, tenant_id: str, partnership_id: str) -> None:
        await self._replicate_with_dependencies(tenant_id, partnership_id, "as2_partnership")

    async def delete_as2_partnership(self, tenant_id: str, partnership_id: str) -> None:
        spec = REPLICATION_GRAPH["as2_partnership"]
        await self._granular_delete(
            tenant_id, partnership_id, spec.data_plane_model, include_shared=spec.include_shared
        )

    async def replicate_sftp_partner(self, tenant_id: str, partner_id: str) -> None:
        await self._replicate_with_dependencies(tenant_id, partner_id, "sftp_partner")

    async def delete_sftp_partner(self, tenant_id: str, partner_id: str) -> None:
        spec = REPLICATION_GRAPH["sftp_partner"]
        await self._granular_delete(
            tenant_id, partner_id, spec.data_plane_model, include_shared=spec.include_shared
        )

    async def replicate_webhook(self, tenant_id: str, webhook_id: str) -> None:
        await self._replicate_with_dependencies(tenant_id, webhook_id, "webhook")

    async def delete_webhook(self, tenant_id: str, webhook_id: str) -> None:
        spec = REPLICATION_GRAPH["webhook"]
        await self._granular_delete(
            tenant_id, webhook_id, spec.data_plane_model, include_shared=spec.include_shared
        )

    async def replicate_inbound_route(self, tenant_id: str, route_id: str) -> None:
        await self._replicate_with_dependencies(tenant_id, route_id, "inbound_route")

    async def delete_inbound_route(self, tenant_id: str, route_id: str) -> None:
        spec = REPLICATION_GRAPH["inbound_route"]
        await self._granular_delete(
            tenant_id, route_id, spec.data_plane_model, include_shared=spec.include_shared
        )

    async def replicate_outbound_route(self, tenant_id: str, route_id: str) -> None:
        await self._replicate_with_dependencies(tenant_id, route_id, "outbound_route")

    async def delete_outbound_route(self, tenant_id: str, route_id: str) -> None:
        spec = REPLICATION_GRAPH["outbound_route"]
        await self._granular_delete(
            tenant_id, route_id, spec.data_plane_model, include_shared=spec.include_shared
        )

    async def replicate_outbound_edi_header(self, tenant_id: str, header_id: str) -> None:
        await self._replicate_with_dependencies(tenant_id, header_id, "outbound_edi_header")

    async def delete_outbound_edi_header(self, tenant_id: str, header_id: str) -> None:
        spec = REPLICATION_GRAPH["outbound_edi_header"]
        await self._granular_delete(
            tenant_id, header_id, spec.data_plane_model, include_shared=spec.include_shared
        )

    # -----------------------------------------------------------------------
    # Private Infrastructure Helpers
    # -----------------------------------------------------------------------

    async def _upsert_batch(
        self,
        tenant_session: AsyncSession,
        rows_data: list[dict[str, object]],
        tenant_model: type[DeclarativeBase],
        chunk_size: int = 100,
    ) -> None:
        """
        Batches and upserts multiple mapped rows into the tenant shard.
        Uses multi-row insert and conflict update using stmt.excluded.
        Chunks large batches to limit statement size.
        """
        if not rows_data:
            return

        for i in range(0, len(rows_data), chunk_size):
            chunk = rows_data[i : i + chunk_size]
            stmt = insert(tenant_model).values(chunk)
            update_cols = {k: getattr(stmt.excluded, k) for k in chunk[0] if k != "id"}
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols)
            await tenant_session.execute(stmt)

    async def _upsert_entity(
        self,
        tenant_session: AsyncSession,
        tenant_id: str,
        global_entity: DeclarativeBase | ReplicatedModel,
        tenant_model: type[DeclarativeBase],
        mapper: MapperFunc,
    ) -> None:
        """
        Materializes a global entity into the tenant shard via UPSERT.
        Preserves the source entity's tenant_id for shared platform entities;
        falls back to the requesting tenant_id only when strictly absent.
        """
        data = dict(mapper(global_entity))
        if data.get("tenant_id") is None:
            data["tenant_id"] = tenant_id

        await self._upsert_batch(tenant_session, [data], tenant_model)
        logger.debug(
            "replication_entity_upserted",
            tenant_model=tenant_model.__name__,
            entity_id=data.get("id"),
            tenant_id=tenant_id,
        )

    async def _granular_delete(
        self,
        tenant_id: str,
        entity_id: str,
        tenant_model: type[ReplicatedModel],
        include_shared: bool = False,
    ) -> None:
        """Deletes a single entity from the tenant shard by ID."""
        async with self._get_tenant_session(tenant_id) as tenant_session:
            try:
                stmt = delete(tenant_model).where(tenant_model.id == entity_id)
                if include_shared:
                    stmt = stmt.where(
                        (tenant_model.tenant_id == tenant_id)
                        | (tenant_model.tenant_id == SHARED_TENANT_ID)
                    )
                else:
                    stmt = stmt.where(tenant_model.tenant_id == tenant_id)

                await tenant_session.execute(stmt)
                await tenant_session.commit()
                logger.info(
                    "replication_entity_deleted",
                    tenant_model=tenant_model.__name__,
                    entity_id=entity_id,
                    tenant_id=tenant_id,
                )
            except Exception as e:
                await tenant_session.rollback()
                logger.exception(
                    "replication_entity_delete_failed",
                    tenant_model=tenant_model.__name__,
                    entity_id=entity_id,
                    tenant_id=tenant_id,
                    reason=str(e),
                )
                raise TransientProvisioningError(
                    f"Failed to delete {tenant_model.__name__} id={entity_id}: {e}"
                ) from e

    async def _sync_deletes(
        self,
        tenant_id: str,
        global_session: AsyncSession,
        tenant_session: AsyncSession,
        global_model: type[ReplicatedModel],
        tenant_model: type[ReplicatedModel],
        include_shared: bool,
    ) -> None:
        """
        Removes stale shard records that no longer exist in the global DB.
        Called during full-sync in reverse topological order to avoid FK violations.
        """
        global_stmt = select(global_model.id).where(global_model.tenant_id == tenant_id)
        if include_shared:
            global_stmt = select(global_model.id).where(
                (global_model.tenant_id == tenant_id) | (global_model.tenant_id == SHARED_TENANT_ID)
            )

        global_ids: set[str] = set((await global_session.execute(global_stmt)).scalars().all())

        tenant_filter = tenant_model.tenant_id == tenant_id
        if include_shared:
            tenant_filter = (tenant_model.tenant_id == tenant_id) | (
                tenant_model.tenant_id == SHARED_TENANT_ID
            )

        tenant_ids: set[str] = set(
            (await tenant_session.execute(select(tenant_model.id).where(tenant_filter)))
            .scalars()
            .all()
        )

        stale_ids = tenant_ids - global_ids
        if stale_ids:
            logger.info(
                "replication_stale_records_removed",
                count=len(stale_ids),
                table=tenant_model.__tablename__,
                tenant_id=tenant_id,
            )
            await tenant_session.execute(
                delete(tenant_model).where(tenant_model.id.in_(list(stale_ids)))
            )


# ---------------------------------------------------------------------------
# Private module-level helper
# ---------------------------------------------------------------------------


def _build_fetch_all_stmt(spec: EntitySpec, tenant_id: str) -> Select[tuple[ReplicatedModel]]:
    """Constructs the SELECT statement for fetching all global entities of a given spec."""
    spec_model = cast(type[ReplicatedModel], spec.control_plane_model)
    if spec.include_shared:
        return select(spec_model).where(
            (spec_model.tenant_id == tenant_id) | (spec_model.tenant_id == SHARED_TENANT_ID)
        )
    return select(spec_model).where(spec_model.tenant_id == tenant_id)
