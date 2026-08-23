"""
SQLAlchemy Replication Adapter.

Implements the ReplicationPort by reading the REPLICATION_GRAPH declarative
registry and driving entity replication in the topologically correct order.

Design invariants:
    - This adapter contains zero hardcoded entity or dependency knowledge.
      All FK dependency semantics live in replication_registry.py.
    - The topological_layers algorithm (in replication_graph.py) is the single
      authoritative source of insertion and deletion order.
    - Every public method delegates to one of two generic drivers:
        _replicate_with_dependencies  (granular: one entity at a time)
        _do_replicate                 (bulk: full tenant state sync)
"""

from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from typing import Any, ClassVar, Protocol, cast

import structlog
from edi.adapters.outbound.database.connection import DatabaseRouter
from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped

from worker.adapters.replication_registry import REPLICATION_GRAPH
from worker.core.errors import PermanentProvisioningError, TransientProvisioningError
from worker.core.replication_graph import EntitySpec, topological_layers
from worker.ports.outbound.replication_port import ReplicationPort
from worker.ports.outbound.tenant_port import TenantPort

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

                        for entity in entities:
                            source_tenant_id = getattr(entity, "tenant_id", None) or tenant_id
                            await self._upsert_entity(
                                tenant_session, source_tenant_id, entity, spec.tenant_model
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
                            spec.global_model,
                            spec.tenant_model,
                            spec.include_shared,
                        )

                await tenant_session.commit()
                logger.info(
                    "[REPLICATION] Successfully performed full state sync for tenant={tenant_id}."
                )

            except Exception as e:
                await tenant_session.rollback()
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
        except Exception as e:
            raise PermanentProvisioningError("Tenant {tenant_id} unresolvable: {e}") from e

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
        except Exception as e:
            raise PermanentProvisioningError("Tenant {tenant_id} unresolvable: {e}") from e

        tenant_gen = self.db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)
        async with aclosing(tenant_gen) as tenant_ctx:
            tenant_session = await tenant_ctx.__anext__()
            yield tenant_session

    # -----------------------------------------------------------------------
    # Generic Granular Replication Driver  (dependency-aware, one entity)
    # -----------------------------------------------------------------------

    async def _replicate_with_dependencies(
        self, tenant_id: str, entity_id: str, entity_key: str
    ) -> None:
        """
        Granular replication driver. Reads the REPLICATION_GRAPH spec for the
        given entity key, pre-replicates all non-null FK dependencies to the
        tenant shard, then upserts the entity itself.

        All public replicate_* methods delegate here. Adding a new entity type
        never requires changing this method — only replication_registry.py.
        """
        spec = REPLICATION_GRAPH[entity_key]

        async with self._get_sessions(tenant_id) as (global_session, tenant_session):
            try:
                # 1. Fetch the entity from the global DB with correct tenant scoping
                entity = await self._fetch_global_entity(global_session, spec, tenant_id, entity_id)

                # 2. Resolve and pre-replicate each declared FK dependency
                for dep in spec.dependencies:
                    dep_id: str | None = getattr(entity, dep.fk_attr, None)
                    if not dep_id:
                        continue  # Optional FK not set on this instance — skip

                    logger.info(
                        "[REPLICATION] {spec.global_model.__name__} {entity_id}: "
                        "FK {dep.fk_attr}={dep_id} → pre-replicating "
                        "{dep.global_model.__name__} to shard for tenant={tenant_id}."
                    )

                    dep_stmt = select(dep.global_model).where(dep.global_model.id == dep_id)
                    dep_res = await global_session.execute(dep_stmt)
                    dep_entity = dep_res.scalars().first()

                    if not dep_entity:
                        raise PermanentProvisioningError(
                            "FK dependency {dep.global_model.__name__} id={dep_id} "
                            "(required by {spec.global_model.__name__} id={entity_id}) "
                            "not found in global DB. The row may have been deleted. "
                            "Sending to DLQ."
                        )

                    dep_tenant_id = getattr(dep_entity, "tenant_id", None) or tenant_id
                    await self._upsert_entity(
                        tenant_session, dep_tenant_id, dep_entity, dep.tenant_model
                    )
                    logger.info(
                        "[REPLICATION] Pre-replicated dependency "
                        "{dep.global_model.__name__} id={dep_id} "
                        "to shard for tenant={dep_tenant_id}."
                    )

                # 3. Upsert the entity — all FK dependencies are now guaranteed to exist
                source_tenant_id = getattr(entity, "tenant_id", None) or tenant_id
                await self._upsert_entity(
                    tenant_session, source_tenant_id, entity, spec.tenant_model
                )
                await tenant_session.commit()
                logger.info(
                    "[REPLICATION] Replicated {spec.global_model.__name__} "
                    "id={entity_id} to shard for tenant={tenant_id}."
                )

            except (TransientProvisioningError, PermanentProvisioningError):
                await tenant_session.rollback()
                raise
            except Exception as e:
                await tenant_session.rollback()
                raise TransientProvisioningError(
                    "Failed to replicate {spec.global_model.__name__} id={entity_id}: {e}"
                ) from e

    async def _fetch_global_entity(
        self,
        global_session: AsyncSession,
        spec: EntitySpec,
        tenant_id: str,
        entity_id: str,
    ) -> DeclarativeBase:
        """Fetches a single entity from the global DB with correct tenant scoping."""
        stmt = select(spec.global_model).where(spec.global_model.id == entity_id)
        if spec.include_shared:
            stmt = stmt.where(
                (spec.global_model.tenant_id == tenant_id)
                | (spec.global_model.tenant_id == SHARED_TENANT_ID)
            )
        else:
            stmt = stmt.where(spec.global_model.tenant_id == tenant_id)

        res = await global_session.execute(stmt)
        entity = res.scalars().first()

        if not entity:
            raise PermanentProvisioningError(
                "{spec.global_model.__name__} id={entity_id} not found "
                "in global DB for tenant={tenant_id}."
            )
        return cast(DeclarativeBase, entity)

    # -----------------------------------------------------------------------
    # Public Granular Replication Methods
    # Each is a single-line delegation to _replicate_with_dependencies.
    # -----------------------------------------------------------------------

    async def replicate_as2_partner(self, tenant_id: str, partner_id: str) -> None:
        await self._replicate_with_dependencies(tenant_id, partner_id, "as2_partner")

    async def delete_as2_partner(self, tenant_id: str, partner_id: str) -> None:
        await self._granular_delete(
            tenant_id, partner_id, REPLICATION_GRAPH["as2_partner"].tenant_model
        )

    async def replicate_as2_partnership(self, tenant_id: str, partnership_id: str) -> None:
        await self._replicate_with_dependencies(tenant_id, partnership_id, "as2_partnership")

    async def delete_as2_partnership(self, tenant_id: str, partnership_id: str) -> None:
        await self._granular_delete(
            tenant_id, partnership_id, REPLICATION_GRAPH["as2_partnership"].tenant_model
        )

    async def replicate_sftp_partner(self, tenant_id: str, partner_id: str) -> None:
        await self._replicate_with_dependencies(tenant_id, partner_id, "sftp_partner")

    async def delete_sftp_partner(self, tenant_id: str, partner_id: str) -> None:
        await self._granular_delete(
            tenant_id, partner_id, REPLICATION_GRAPH["sftp_partner"].tenant_model
        )

    async def replicate_webhook(self, tenant_id: str, webhook_id: str) -> None:
        await self._replicate_with_dependencies(tenant_id, webhook_id, "webhook")

    async def delete_webhook(self, tenant_id: str, webhook_id: str) -> None:
        await self._granular_delete(
            tenant_id, webhook_id, REPLICATION_GRAPH["webhook"].tenant_model
        )

    async def replicate_inbound_route(self, tenant_id: str, route_id: str) -> None:
        await self._replicate_with_dependencies(tenant_id, route_id, "inbound_route")

    async def delete_inbound_route(self, tenant_id: str, route_id: str) -> None:
        await self._granular_delete(
            tenant_id, route_id, REPLICATION_GRAPH["inbound_route"].tenant_model
        )

    async def replicate_outbound_route(self, tenant_id: str, route_id: str) -> None:
        await self._replicate_with_dependencies(tenant_id, route_id, "outbound_route")

    async def delete_outbound_route(self, tenant_id: str, route_id: str) -> None:
        await self._granular_delete(
            tenant_id, route_id, REPLICATION_GRAPH["outbound_route"].tenant_model
        )

    async def replicate_outbound_edi_header(self, tenant_id: str, header_id: str) -> None:
        await self._replicate_with_dependencies(tenant_id, header_id, "outbound_edi_header")

    async def delete_outbound_edi_header(self, tenant_id: str, header_id: str) -> None:
        await self._granular_delete(
            tenant_id, header_id, REPLICATION_GRAPH["outbound_edi_header"].tenant_model
        )

    # -----------------------------------------------------------------------
    # Private Infrastructure Helpers
    # -----------------------------------------------------------------------

    async def _upsert_entity(
        self,
        tenant_session: AsyncSession,
        tenant_id: str,
        global_entity: DeclarativeBase,
        tenant_model: type[DeclarativeBase],
    ) -> None:
        """
        Materializes a global entity into the tenant shard via UPSERT.
        Preserves the source entity's tenant_id for shared platform entities;
        falls back to the requesting tenant_id only when strictly absent.
        """
        tenant_columns: set[str] = {col.name for col in tenant_model.__table__.columns}

        data: dict[str, object] = {
            col.name: getattr(global_entity, col.name)
            for col in global_entity.__table__.columns
            if hasattr(global_entity, col.name) and col.name in tenant_columns
        }

        if data.get("tenant_id") is None:
            data["tenant_id"] = tenant_id

        stmt = insert(tenant_model).values(**data)
        update_cols = {k: v for k, v in data.items() if k != "id"}
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols)

        logger.debug(
            "[REPLICATION] Upserting {tenant_model.__name__} id={data.get('id')} "
            "into shard for tenant={tenant_id}."
        )
        await tenant_session.execute(stmt)

    async def _granular_delete(
        self,
        tenant_id: str,
        entity_id: str,
        tenant_model: type[ReplicatedModel],
    ) -> None:
        """Deletes a single entity from the tenant shard by ID."""
        async with self._get_tenant_session(tenant_id) as tenant_session:
            try:
                await tenant_session.execute(
                    delete(tenant_model).where(
                        tenant_model.id == entity_id,
                        tenant_model.tenant_id == tenant_id,
                    )
                )
                await tenant_session.commit()
                logger.info(
                    "[REPLICATION] Deleted {tenant_model.__name__} id={entity_id} "
                    "from shard for tenant={tenant_id}."
                )
            except Exception as e:
                await tenant_session.rollback()
                raise TransientProvisioningError(
                    "Failed to delete {tenant_model.__name__} id={entity_id}: {e}"
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
                "[REPLICATION] Removing {len(stale_ids)} stale "
                "{tenant_model.__tablename__} record(s) from shard for tenant={tenant_id}."
            )
            await tenant_session.execute(
                delete(tenant_model).where(tenant_model.id.in_(list(stale_ids)))
            )


# ---------------------------------------------------------------------------
# Private module-level helper
# ---------------------------------------------------------------------------


def _build_fetch_all_stmt(spec: EntitySpec, tenant_id: str) -> Any:
    """Constructs the SELECT statement for fetching all global entities of a given spec."""
    if spec.include_shared:
        return select(spec.global_model).where(
            (spec.global_model.tenant_id == tenant_id)
            | (spec.global_model.tenant_id == SHARED_TENANT_ID)
        )
    return select(spec.global_model).where(spec.global_model.tenant_id == tenant_id)
